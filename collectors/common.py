"""Shared helpers for the collectors.

Stdlib only and Python 3.9 compatible: the status line, hook and meter run
under /usr/bin/python3 so a python.org upgrade can never break them.
"""
import json
import os
import time

METER_ENV = "CLAUDE_USAGE_GRID_METER"
MAX_ERROR_LOG_BYTES = 512 * 1024


def data_dir():
    """~/.claude-usage-grid, or CLAUDE_USAGE_GRID_HOME (used by the tests)."""
    return os.path.expanduser(os.environ.get("CLAUDE_USAGE_GRID_HOME") or "~/.claude-usage-grid")


def path(*parts):
    return os.path.join(data_dir(), *parts)


def now():
    """Epoch seconds. CLAUDE_USAGE_GRID_NOW pins the clock in tests."""
    pinned = os.environ.get("CLAUDE_USAGE_GRID_NOW")
    return float(pinned) if pinned else time.time()


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_window(window):
    """A status-line window -> {"used_percentage", "resets_at"}, or None if unusable."""
    if not isinstance(window, dict) or not is_number(window.get("used_percentage")):
        return None
    resets_at = window.get("resets_at")
    return {
        "used_percentage": window["used_percentage"],
        "resets_at": int(resets_at) if is_number(resets_at) else None,
    }


def append_jsonl(file_path, record):
    """Append one JSON line with a single O_APPEND write so concurrent writers never interleave."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    fd = os.open(file_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def read_json(file_path, default=None):
    try:
        with open(file_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json_atomic(file_path, obj):
    """Write via a temp file and rename, so readers never see a half-written file."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    tmp = "%s.%d.tmp" % (file_path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, file_path)


def log_error(where, exc):
    """Record a collector error. Never raises: collectors must not break Claude Code."""
    try:
        log_path = path("logs", "errors.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        if os.path.exists(log_path) and os.path.getsize(log_path) > MAX_ERROR_LOG_BYTES:
            os.replace(log_path, log_path + ".1")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("%s %s: %s: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), where, type(exc).__name__, exc))
    except Exception:
        pass
