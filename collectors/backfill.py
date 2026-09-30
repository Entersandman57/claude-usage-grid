#!/usr/bin/env python3
"""Refresh sessions.json from the Agent SDK's documented list_sessions().

Keeps IDs, titles, folders and timestamps only. The title is `custom_title`
(your title or the AI-generated one); `summary` and `first_prompt` are never
read because they can hold prompt text. Sessions whose transcripts are gone
(Claude Code deletes them after cleanupPeriodDays) stay listed with
transcript_present = false, so their days and titles survive.

Runs in the SDK venv (Python 3.10+): ~/.claude-usage-grid/venv/bin/python.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def _seconds(ms):
    return round(ms / 1000.0, 3) if common.is_number(ms) else None


def session_record(info):
    return {
        "session_id": info.session_id,
        "title": info.custom_title or None,
        "cwd": info.cwd,
        "created_at": _seconds(info.created_at),
        "last_modified": _seconds(info.last_modified),
        "transcript_present": True,
    }


def merge(existing, listed, ts):
    """Update known sessions with the listed ones; keep the rest as transcript-less."""
    sessions = {sid: dict(rec) for sid, rec in existing.items()}
    listed_ids = set()
    for rec in listed:
        sid = rec["session_id"]
        listed_ids.add(sid)
        previous = sessions.get(sid, {})
        rec["title"] = rec["title"] or previous.get("title")
        rec["first_seen"] = previous.get("first_seen", ts)
        sessions[sid] = rec
    for sid, rec in sessions.items():
        if sid not in listed_ids:
            rec["transcript_present"] = False
    return sessions


def main():
    from claude_agent_sdk import list_sessions

    ts = round(common.now(), 3)
    listed = [session_record(info) for info in list_sessions()]
    out_path = common.path("sessions.json")
    existing = (common.read_json(out_path, {}) or {}).get("sessions") or {}
    sessions = merge(existing, listed, ts)
    common.write_json_atomic(out_path, {"updated_at": ts, "sessions": sessions})
    present = sum(1 for rec in sessions.values() if rec["transcript_present"])
    print("sessions.json: %d sessions (%d with transcripts)" % (len(sessions), present))


if __name__ == "__main__":
    main()
