#!/usr/bin/env python3
"""Chats and plan-usage samples from the Claude desktop app's local data.

Reads two things under ~/Library/Application Support/Claude, always from a
temporary copy (an APFS clone) that is deleted afterwards; the app's folder is
never written to:

  * Cache/Cache_Data: Chromium's HTTP cache. The app's cached chat lists
    (chat_conversations_v2) give each chat's ID, title and timestamps; cached
    full conversations give their messages' dates. Each scan adds the chat's
    latest-activity day, so scanning often records every day a chat was used.
    Only entries whose URL is a chat list or conversation are read past their
    key. Nothing else (cookies, local storage, drafts, config) is opened.
  * plan-usage-history.json: the app's own 5-hour and weekly % samples, added
    to readings.jsonl as source "app_history" (no reset times).

Keeps only chat IDs, titles and days (app-chats.json); never message text or
summaries, which are parsed in memory and dropped. Undocumented formats: if
they change, the scan finds nothing and says so. Needs Python 3.14+ (zstd), so
it runs in the SDK venv. Prints a JSON summary of counts.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

APP_DIR = os.path.expanduser("~/Library/Application Support/Claude")
ENTRY_MAGIC = 0xfcfb6d1ba7725c30
EOF_MAGIC = 0xf4fa6f45970d41d8
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
LIST_URL = re.compile(r"https://claude\.ai/api/organizations/" + UUID + r"/(?:projects/" + UUID + r"/)?"
                      r"(?:chat_)?conversations_v2(?:\?|$)")
CONVERSATION_URL = re.compile(r"https://claude\.ai/api/organizations/" + UUID + r"/chat_conversations/(" + UUID
                              + r")(?:\?|$)")
CHAT_ID = re.compile(UUID)


def app_dir():
    return os.environ.get("CLAUDE_USAGE_GRID_APP_DIR") or APP_DIR


def clone(source, target):
    """An APFS clone (copy-on-write, near instant), falling back to a plain copy."""
    if subprocess.run(["/bin/cp", "-cR", source, target], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode != 0:
        if os.path.isdir(source):
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)


# --- the HTTP cache ------------------------------------------------------------------------

def entry_key(path):
    """The cache entry's key (its URL), from the 24-byte header; the body isn't read."""
    with open(path, "rb") as f:
        head = f.read(24)
        if len(head) < 24:
            return None
        magic, _version, key_length, _hash, _pad = struct.unpack("<QIIII", head)
        if magic != ENTRY_MAGIC or key_length > 8192:
            return None
        key = f.read(key_length).decode("utf-8", "replace")
    return key[key.find("http"):] if "http" in key else None


def entry_body(path):
    """The response body, decoded (zstd, gzip or none), or None."""
    with open(path, "rb") as f:
        data = f.read()
    key_length = struct.unpack("<I", data[12:16])[0]
    magic, flags, _crc, stream0_size = struct.unpack("<QIII", data[-24:-4])
    if magic != EOF_MAGIC:
        return None
    stream0_end = len(data) - 24 - (32 if flags & 2 else 0)
    stream0_start = stream0_end - stream0_size
    if struct.unpack("<Q", data[stream0_start - 24:stream0_start - 16])[0] != EOF_MAGIC:
        return None
    body = data[24 + key_length:stream0_start - 24]
    encoding = re.search(rb"\x00content-encoding:\s*([^\x00]*)", data[stream0_start:stream0_end], re.I)
    encoding = encoding.group(1).strip().lower() if encoding else b""
    if encoding == b"zstd":
        from compression import zstd
        body = zstd.decompress(body)
    elif encoding == b"gzip":
        import gzip
        body = gzip.decompress(body)
    elif encoding:
        return None
    return json.loads(body)


def local_day(timestamp):
    """ISO time (UTC, "Z") -> local YYYY-MM-DD, or None."""
    if not isinstance(timestamp, str):
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return None


def chats_from_cache(cache_dir):
    """{uuid: {"uuid", "title", "days"}} from cached chat lists and conversations."""
    chats = {}

    def add(uuid, title, days):
        chat = chats.setdefault(uuid, {"uuid": uuid, "title": None, "days": set()})
        chat["title"] = title if isinstance(title, str) and title else chat["title"]
        chat["days"].update(d for d in days if d)

    for name in os.listdir(cache_dir):
        if not name.endswith("_0"):
            continue
        path = os.path.join(cache_dir, name)
        try:
            url = entry_key(path)
            if url is None:
                continue
            if LIST_URL.match(url):
                data = entry_body(path)
                for item in (data or {}).get("data") or []:
                    if not isinstance(item, dict) or not CHAT_ID.fullmatch(str(item.get("uuid", ""))):
                        continue
                    if item.get("has_assistant_outputs") is False:
                        continue  # opened, never answered (the export import skips these too)
                    last = item.get("latest_assistant_output_at") or item.get("updated_at")
                    add(item["uuid"], item.get("name"), [local_day(item.get("created_at")), local_day(last)])
            else:
                match = CONVERSATION_URL.match(url)
                if match:
                    data = entry_body(path) or {}
                    days = [local_day(m.get("created_at")) for m in data.get("chat_messages") or []
                            if isinstance(m, dict)]
                    if days:
                        add(match.group(1), data.get("name"), days)
        except Exception:  # a half-written or unexpected entry: skip it
            continue
    return chats


def merge_chats(found, now_ts):
    """Add newly seen chats and days to app-chats.json. Returns (chats seen, new days)."""
    path = common.path("app-chats.json")
    store = common.read_json(path, {}) or {}
    chats = store.get("chats") or {}
    added = 0
    for uuid, chat in found.items():
        entry = chats.setdefault(uuid, {"uuid": uuid, "title": None, "days": []})
        entry["title"] = chat["title"] or entry.get("title")
        new_days = chat["days"] - set(entry.get("days") or [])
        added += len(new_days)
        entry["days"] = sorted(set(entry.get("days") or []) | chat["days"])
    store.update(chats=chats, scanned_at=now_ts,
                 last_found_at=now_ts if found else store.get("last_found_at"))
    common.write_json_atomic(path, store)
    return len(found), added


# --- plan-usage-history.json ----------------------------------------------------------------

def history_readings(history, after_ms):
    """Readings from the app's samples newer than after_ms (5-hour fh, weekly sd)."""
    readings = []
    for sample in (history or {}).get("samples") or []:
        t, usage = sample.get("t"), sample.get("u") or {}
        if not common.is_number(t) or t <= after_ms:
            continue
        if not (common.is_number(usage.get("fh")) and common.is_number(usage.get("sd"))):
            continue
        readings.append({"ts": round(t / 1000.0, 3), "source": "app_history", "trigger": None,
                         "session_id": None, "session_name": None, "project_dir": None,
                         "five_hour": {"used_percentage": float(usage["fh"]), "resets_at": None},
                         "seven_day": {"used_percentage": float(usage["sd"]), "resets_at": None},
                         "status": None})
    return sorted(readings, key=lambda r: r["ts"])


def import_history(path, state):
    readings = history_readings(common.read_json(path, {}), state.get("history_last_t") or 0)
    for reading in readings:
        common.append_jsonl(common.path("readings.jsonl"), reading)
    if readings:
        state["history_last_t"] = int(readings[-1]["ts"] * 1000)
    return len(readings)


# --- main ----------------------------------------------------------------------------------

def main(argv=None):
    source = app_dir()
    summary = {"ok": True, "chats_seen": 0, "new_chat_days": 0, "history_samples": 0, "error": None}
    state_path = common.path("state", "app-scan.json")
    state = common.read_json(state_path, {}) or {}
    work = tempfile.mkdtemp(prefix="claude-usage-grid-scan-")
    try:
        cache = os.path.join(source, "Cache", "Cache_Data")
        if os.path.isdir(cache):
            clone(cache, os.path.join(work, "cache"))
            summary["chats_seen"], summary["new_chat_days"] = merge_chats(
                chats_from_cache(os.path.join(work, "cache")), round(common.now(), 3))
        history = os.path.join(source, "plan-usage-history.json")
        if os.path.isfile(history):
            clone(history, os.path.join(work, "history.json"))
            summary["history_samples"] = import_history(os.path.join(work, "history.json"), state)
        state["last_scan"] = round(common.now(), 3)
        common.write_json_atomic(state_path, state)
    except Exception as exc:
        summary.update(ok=False, error="%s: %s" % (type(exc).__name__, exc))
        common.log_error("app_scan", exc)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps(summary))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
