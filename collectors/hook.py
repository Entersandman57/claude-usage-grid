#!/usr/bin/env python3
"""Claude Code hook for SessionStart and UserPromptSubmit: records session activity.

Appends {ts, event, session_id, cwd, entrypoint[, source, title]} to activity.jsonl.
Only those fields are read from the hook input; the prompt text is never stored.
Prints nothing (both events feed stdout back to Claude as context) and always
exits 0. Skips the meter's own `claude -p` call (CLAUDE_USAGE_GRID_METER=1).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def build_record(data, event_arg, env, ts):
    event = data.get("hook_event_name") or event_arg
    record = {
        "ts": round(ts, 3),
        "event": event,
        "session_id": data.get("session_id"),
        "cwd": data.get("cwd"),
        "entrypoint": env.get("CLAUDE_CODE_ENTRYPOINT"),
    }
    if event == "SessionStart":
        record["source"] = data.get("source")
        title = data.get("session_title")
        if isinstance(title, str) and title:
            record["title"] = title
    return record


def main():
    if os.environ.get(common.METER_ENV) == "1":
        return
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        if not isinstance(data, dict) or not data.get("session_id"):
            return
        event_arg = sys.argv[1] if len(sys.argv) > 1 else None
        record = build_record(data, event_arg, os.environ, common.now())
        common.append_jsonl(common.path("activity.jsonl"), record)
    except Exception as exc:
        common.log_error("hook", exc)


if __name__ == "__main__":
    main()
