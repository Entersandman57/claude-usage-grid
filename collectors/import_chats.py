#!/usr/bin/env python3
"""Import claude.ai chats from the official data export (Settings > Privacy > Export data).

  import_chats.py <export.zip | conversations.json | unzipped folder>

Keeps only each conversation's uuid, title and the local days it had messages,
merged into ~/.claude-usage-grid/chats.json. Message text is never stored.

The export's schema isn't documented, so parsing is defensive: known field
names and common alternatives are accepted, anything unrecognized is skipped
and counted, and the summary printed as JSON on stdout says what was found.
Chats from earlier imports that are missing from this one (deleted on
claude.ai) are kept. Stdlib only, Python 3.9 compatible.
"""
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ID_KEYS = ("uuid", "id", "conversation_id")
TITLE_KEYS = ("name", "title")
MESSAGE_LIST_KEYS = ("chat_messages", "messages")
MESSAGE_TIME_KEYS = ("created_at", "create_time", "timestamp", "updated_at")
CONVERSATION_TIME_KEYS = ("created_at", "updated_at", "create_time", "update_time")

ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


class ExportError(Exception):
    """A problem with the file itself (not with individual conversations)."""


def parse_time(value):
    """An ISO 8601 string or epoch number (s or ms) -> aware datetime, else None.

    Strings without a time zone are taken as UTC, which is what the export uses.
    """
    if common.is_number(value):
        seconds = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    match = ISO.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    micro = int((fraction or "0")[:6].ljust(6, "0"))
    tz = timezone.utc
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                        int(second or 0), micro, tzinfo=tz)
    except ValueError:
        return None


def local_day(moment):
    return datetime.fromtimestamp(moment.timestamp()).date().isoformat()


def first(mapping, keys):
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def read_conversations(path):
    """(parsed conversations.json, export date or None) from a zip, folder or file."""
    if os.path.isdir(path):
        path = os.path.join(path, "conversations.json")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist()
                       if os.path.basename(m.filename).lower() == "conversations.json" and not m.is_dir()]
            if not members:
                raise ExportError("no conversations.json in this ZIP; is it the claude.ai data export?")
            member = min(members, key=lambda m: len(m.filename))
            with archive.open(member) as f:
                data = json.load(f)
            # Zip times have no zone; the export is made on Anthropic's servers (UTC).
            exported = datetime(*member.date_time, tzinfo=timezone.utc)
            return data, exported
    if not os.path.isfile(path):
        raise ExportError("file not found: %s" % path)
    with open(path, encoding="utf-8") as f:
        return json.load(f), None


def manifest_hint(data):
    """If data is the export's manifest (a list of files to download), say which one to get."""
    if not (isinstance(data, dict) and isinstance(data.get("data_files"), list)):
        return None
    names = [f.get("filename") for f in data["data_files"]
             if isinstance(f, dict) and f.get("category") == "conversations" and f.get("filename")]
    wanted = " and ".join(names) or "the conversations file"
    return ("This is the export's manifest, a list of files to download, not the chats themselves. "
            "Download %s from it (each link works once), then import that." % wanted)


def conversations_from(data):
    hint = manifest_hint(data)
    if hint:
        raise ExportError(hint)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("conversations", "chats", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    raise ExportError("conversations.json isn't a list of conversations")


def summarize(conversation):
    """{uuid, title, days} for one conversation plus how its days were found, or None."""
    if not isinstance(conversation, dict):
        return None, "not an object"
    uuid = first(conversation, ID_KEYS)
    if not isinstance(uuid, str) or not uuid.strip():
        return None, "no id"
    title = first(conversation, TITLE_KEYS)
    title = title.strip() if isinstance(title, str) and title.strip() else None
    days, source = set(), "messages"
    messages = first(conversation, MESSAGE_LIST_KEYS)
    for message in messages if isinstance(messages, list) else []:
        if isinstance(message, dict):
            moment = parse_time(first(message, MESSAGE_TIME_KEYS))
            if moment:
                days.add(local_day(moment))
    if not days:  # no usable message times: fall back to the conversation's own
        source = "conversation times"
        for key in CONVERSATION_TIME_KEYS:
            moment = parse_time(conversation.get(key))
            if moment:
                days.add(local_day(moment))
    if not days:
        return None, "no dates"
    return {"uuid": uuid.strip(), "title": title, "days": sorted(days)}, source


def import_export(path, ts):
    data, exported = read_conversations(path)
    found = conversations_from(data)
    chats, skipped, from_conversation_times = {}, {}, 0
    for conversation in found:
        chat, how = summarize(conversation)
        if chat is None:
            skipped[how] = skipped.get(how, 0) + 1
            continue
        if how == "conversation times":
            from_conversation_times += 1
        chats[chat["uuid"]] = chat

    out_path = common.path("chats.json")
    previous = common.read_json(out_path, {}) or {}
    merged = dict(previous.get("chats") or {})
    merged.update(chats)
    latest = max((day for chat in chats.values() for day in chat["days"]), default=None)
    through_candidates = [d for d in (latest, local_day(exported) if exported else None,
                                      previous.get("imported_through")) if d]
    imported_through = max(through_candidates) if through_candidates else None
    common.write_json_atomic(out_path, {
        "imported_at": round(ts, 3),
        "imported_through": imported_through,
        "export_file": os.path.basename(path),
        "chats": merged,
    })
    return {
        "ok": True,
        "conversations_in_export": len(found),
        "imported": len(chats),
        "skipped": skipped,
        "dated_by_conversation_times": from_conversation_times,
        "first_day": min((d for c in chats.values() for d in c["days"]), default=None),
        "last_day": latest,
        "imported_through": imported_through,
        "total_chats_known": len(merged),
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        summary = import_export(argv[0], common.now())
    except (ExportError, ValueError, OSError, zipfile.BadZipFile) as exc:
        summary = {"ok": False, "error": str(exc)}
    print(json.dumps(summary))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
