#!/usr/bin/env python3
"""Phase 0 probe (a): which surfaces run a status line, and what rate_limits look like there.

Stores no prompt or chat text: only top-level key names, session_id, version,
the surface (CLAUDE_CODE_ENTRYPOINT) and the rate_limits object.
Python 3.9 compatible (runs under /usr/bin/python3).
"""
import json
import os
import sys
import time

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "statusline-probe.jsonl")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    rate_limits = data.get("rate_limits") or {}
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        record = {
            "ts": round(time.time(), 3),
            "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
            "session_id": data.get("session_id"),
            "version": data.get("version"),
            "keys": sorted(data.keys()),
            "rate_limits": rate_limits,
        }
        with open(OUT, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

    def pct(window):
        value = (rate_limits.get(window) or {}).get("used_percentage")
        return "--" if value is None else "%d%%" % round(value)

    print("usage-grid probe · 5h %s · wk %s" % (pct("five_hour"), pct("seven_day")))


main()
