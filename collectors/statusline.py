#!/usr/bin/env python3
"""Claude Code status line: prints "5h N% · wk N%" and logs plan-usage readings.

If you had a status line before installing, config.json names it as
"wrapped_statusline" and its output is printed byte-for-byte instead.

A reading goes to readings.jsonl when either window changes, otherwise at most
once a minute (a heartbeat that shows readings are arriving). Logging happens
after printing and swallows every error, so it can never break the status line.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

HEARTBEAT_SECONDS = 60
WRAPPED_TIMEOUT_SECONDS = 10
WINDOWS = ("five_hour", "seven_day")


def parse_windows(data):
    limits = data.get("rate_limits")
    if not isinstance(limits, dict):
        return {}
    windows = {}
    for name in WINDOWS:
        window = common.normalize_window(limits.get(name))
        if window:
            windows[name] = window
    return windows


def render(windows):
    def pct(name):
        window = windows.get(name)
        return "--" if window is None else "%d%%" % int(window["used_percentage"] + 0.5)

    return "5h %s · wk %s" % (pct("five_hour"), pct("seven_day"))


def wrapped_command():
    config = common.read_json(common.path("config.json"), {}) or {}
    wrapped = config.get("wrapped_statusline") or {}
    return wrapped.get("command") if isinstance(wrapped, dict) else None


def log_reading(data, windows, ts):
    if not windows:
        return
    state_path = common.path("state", "statusline.json")
    state = common.read_json(state_path, {}) or {}
    changed = state.get("windows") != windows
    if not changed and ts - float(state.get("ts") or 0) < HEARTBEAT_SECONDS:
        return
    workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
    common.append_jsonl(common.path("readings.jsonl"), {
        "ts": round(ts, 3),
        "source": "statusline",
        "session_id": data.get("session_id"),
        "session_name": data.get("session_name"),
        "project_dir": workspace.get("project_dir") or data.get("cwd"),
        "five_hour": windows.get("five_hour"),
        "seven_day": windows.get("seven_day"),
        "changed": changed,
    })
    common.write_json_atomic(state_path, {"ts": ts, "windows": windows})


def main():
    raw = b""
    data = {}
    try:
        raw = sys.stdin.buffer.read()
        parsed = json.loads(raw.decode("utf-8") or "{}")
        data = parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        common.log_error("statusline.parse", exc)
    windows = parse_windows(data)

    printed = False
    command = wrapped_command()
    if command:
        try:
            result = subprocess.run(command, shell=True, input=raw, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=WRAPPED_TIMEOUT_SECONDS)
            sys.stdout.buffer.write(result.stdout)
            sys.stderr.buffer.write(result.stderr)
            printed = True
        except Exception as exc:
            common.log_error("statusline.wrapped", exc)
    if not printed:
        sys.stdout.buffer.write((render(windows) + "\n").encode("utf-8"))
    sys.stdout.flush()

    try:
        log_reading(data, windows, common.now())
    except Exception as exc:
        common.log_error("statusline.log", exc)


if __name__ == "__main__":
    main()
