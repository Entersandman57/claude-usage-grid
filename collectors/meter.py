#!/usr/bin/env python3
"""Plan-usage readings ("meter") from the smallest possible `claude -p` call.

launchd starts `meter.py --scheduled` every hour at :55. It makes at most one
automatic call per slot:
  * every meter_interval_hours (config.json, default 3) counting back from
    23:55, so 02:55, 05:55 ... 20:55 and 23:55, the day's last reading;
  * on the day the weekly window resets, also the last :55 wake-up before the
    reset, so the day's pre-reset usage is read before the window starts over.
A slot missed while the Mac was asleep runs on wake, until the next slot starts
or midnight, whichever is first; a failed call is never retried. `meter.py
--now` takes a manual reading and does not use up a slot.

Both windows come from the stream-json rate_limit_event's `unifiedWindows`
(undocumented; 0-1 fractions, stored as 0-100 percentages like the status
line). The documented top-level rateLimitType/utilization pair is the fallback.
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as clock, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

WEEK_SECONDS = 7 * 24 * 3600
SLOT_MINUTE = 55
LAST_SLOT_HOUR = 23  # every day's last automatic reading is at 23:55
DEFAULT_INTERVAL_HOURS = 3
PRE_RESET_MARGIN = timedelta(minutes=3)
RESET_GUARD = timedelta(seconds=60)
LAUNCHD_SLACK = timedelta(seconds=30)
RUN_TIMEOUT_SECONDS = 120
BACKFILL_TIMEOUT_SECONDS = 120
WINDOWS = ("five_hour", "seven_day")

PROMPT = "Reply with the single word: ok"
SYSTEM_PROMPT = "Reply with exactly one word."


def local(ts):
    """Naive local wall-clock time, the clock launchd schedules by."""
    return datetime.fromtimestamp(ts)


def upcoming_reset(known_reset, now_ts):
    """Project a known weekly reset forward in whole weeks to the first one after now."""
    if not common.is_number(known_reset):
        return None
    reset = int(known_reset)
    if reset <= now_ts:
        reset += ((int(now_ts) - reset) // WEEK_SECONDS + 1) * WEEK_SECONDS
    return reset


def pre_reset_slot(reset):
    """The last hh:55 wake-up at least PRE_RESET_MARGIN before the reset."""
    latest = reset - PRE_RESET_MARGIN
    slot = latest.replace(minute=SLOT_MINUTE, second=0, microsecond=0)
    if slot > latest:
        slot -= timedelta(hours=1)
    return slot


def interval_hours(config):
    """Hours between automatic readings: config.json's meter_interval_hours (1-24), default 3."""
    value = config.get("meter_interval_hours", DEFAULT_INTERVAL_HOURS)
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 24:
        return value
    return DEFAULT_INTERVAL_HOURS


def regular_slots(day, interval):
    """The day's hh:55 slots: 23:55 and every `interval` hours before it."""
    return [datetime.combine(day, clock(hour, SLOT_MINUTE))
            for hour in range(LAST_SLOT_HOUR % interval, 24, interval)]


def due_run(now_ts, last_slot, known_reset, interval=DEFAULT_INTERVAL_HOURS):
    """(trigger, slot) for the automatic run due at now_ts, or None.

    The slot is the latest of today's slots that has started (launchd may wake
    a few seconds early), as "YYYY-MM-DDTHH:MM"; it is due unless last_slot is
    the same or later. trigger is "pre_reset" for the slot before a weekly
    reset, otherwise "scheduled".
    """
    now = local(now_ts)
    soon = now + LAUNCHD_SLACK
    candidates = [(slot, "scheduled") for slot in regular_slots(now.date(), interval) if slot <= soon]
    reset_ts = upcoming_reset(known_reset, now_ts)
    if reset_ts is not None:
        reset = local(reset_ts)
        slot = pre_reset_slot(reset)
        if reset.date() == now.date() == slot.date() and slot <= soon and now < reset - RESET_GUARD:
            candidates.append((slot, "pre_reset"))
    if not candidates:
        return None
    slot, trigger = max(candidates, key=lambda candidate: (candidate[0], candidate[1] == "pre_reset"))
    slot_id = slot.strftime("%Y-%m-%dT%H:%M")
    if last_slot and last_slot >= slot_id:
        return None
    return trigger, slot_id


def last_auto_slot(state):
    """The last automatic slot run. State from the once-a-day meter has no
    last_auto_slot, so its last automatic run's time stands in."""
    if state.get("last_auto_slot"):
        return state["last_auto_slot"]
    run = state.get("last_run") or {}
    if run.get("trigger") in ("nightly", "pre_reset") and common.is_number(run.get("ts")):
        return local(run["ts"]).strftime("%Y-%m-%dT%H:%M")
    return None


def known_weekly_reset(meter_state):
    """The most recently observed weekly resets_at, from the meter or the status line."""
    seen = []
    weekly = meter_state.get("weekly_reset") or {}
    if common.is_number(weekly.get("resets_at")):
        seen.append((weekly.get("seen_ts") or 0, weekly["resets_at"]))
    statusline = common.read_json(common.path("state", "statusline.json"), {}) or {}
    seven_day = (statusline.get("windows") or {}).get("seven_day") or {}
    if common.is_number(seven_day.get("resets_at")):
        seen.append((statusline.get("ts") or 0, seven_day["resets_at"]))
    return max(seen)[1] if seen else None


def _window(utilization, resets_at):
    return {
        "used_percentage": round(utilization * 100.0, 2),
        "resets_at": int(resets_at) if common.is_number(resets_at) else None,
    }


def parse_rate_limit_info(info):
    """rate_limit_info -> {"five_hour": {...}, "seven_day": {...}} with whatever is present."""
    if not isinstance(info, dict):
        return {}
    windows = {}
    unified = info.get("unifiedWindows")
    if isinstance(unified, dict):
        for name in WINDOWS:
            window = unified.get(name)
            if isinstance(window, dict) and common.is_number(window.get("utilization")):
                windows[name] = _window(window["utilization"], window.get("resetsAt"))
    name = info.get("rateLimitType")
    if name in WINDOWS and name not in windows:
        if common.is_number(info.get("utilization")):
            windows[name] = _window(info["utilization"], info.get("resetsAt"))
        elif info.get("status") == "rejected":  # refused for this window: it's at its limit
            windows[name] = _window(1.0, info.get("resetsAt"))
    return windows


def parse_stream(stdout_text):
    """(windows, status, error, cost_usd) from stream-json output. Keeps no reply text."""
    windows, status, error, cost = {}, None, None, None
    for line in stdout_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info")
            windows.update(parse_rate_limit_info(info))
            if isinstance(info, dict) and isinstance(info.get("status"), str):
                status = info["status"]
        elif event.get("type") == "result":
            if common.is_number(event.get("total_cost_usd")):
                cost = event["total_cost_usd"]
            if event.get("is_error"):
                error = str(event.get("result") or event.get("subtype") or "error")[:300]
    return windows, status, error, cost


def claude_command(claude_bin):
    return [claude_bin, "-p", PROMPT,
            "--model", "haiku", "--no-session-persistence",
            "--output-format", "stream-json", "--verbose",
            "--tools", "", "--strict-mcp-config",
            "--system-prompt", SYSTEM_PROMPT, "--max-turns", "1"]


def clean_env():
    """A minimal, launchd-like environment, tagged so our hook ignores this call."""
    env = {"HOME": os.path.expanduser("~"), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
           "LANG": "en_US.UTF-8", common.METER_ENV: "1"}
    for key in ("USER", "LOGNAME", "TMPDIR"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def take_reading(trigger, config):
    claude_bin = os.path.expanduser(config.get("claude_bin") or "~/.local/bin/claude")
    timeout = config.get("meter_timeout_seconds") or RUN_TIMEOUT_SECONDS
    cwd = common.path("meter-cwd")
    os.makedirs(cwd, exist_ok=True)
    run = {"ts": None, "trigger": trigger, "ok": False, "error": None, "windows": [],
           "status": None, "cost_usd": None, "duration_s": None}
    windows = {}
    started = time.monotonic()
    try:
        proc = subprocess.run(claude_command(claude_bin), cwd=cwd, env=clean_env(),
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
        windows, run["status"], run["error"], run["cost_usd"] = parse_stream(
            proc.stdout.decode("utf-8", "replace"))
        if not windows and not run["error"]:
            run["error"] = "no utilization in output (exit %d)" % proc.returncode
    except subprocess.TimeoutExpired:
        run["error"] = "timed out after %ss" % timeout
    except OSError as exc:
        run["error"] = "could not start %s: %s" % (claude_bin, exc)

    ts = round(common.now(), 3)
    run.update(ts=ts, ok=bool(windows), windows=sorted(windows),
               duration_s=round(time.monotonic() - started, 2))
    if windows:
        common.append_jsonl(common.path("readings.jsonl"), {
            "ts": ts, "source": "meter", "trigger": trigger,
            "session_id": None, "session_name": None, "project_dir": None,
            "five_hour": windows.get("five_hour"), "seven_day": windows.get("seven_day"),
            "status": run["status"],
        })
    common.append_jsonl(common.path("meter-runs.jsonl"), run)
    return run, windows


def refresh_sessions():
    """Best effort: refresh sessions.json with the SDK venv after a scheduled run."""
    python = common.path("venv", "bin", "python")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backfill.py")
    if not (os.path.exists(python) and os.path.exists(script)):
        return
    try:
        subprocess.run([python, script], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                       timeout=BACKFILL_TIMEOUT_SECONDS, check=True)
    except Exception as exc:
        common.log_error("meter.backfill", exc)


def acquire_lock():
    lock_path = common.path("state", "meter.lock")
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Take a plan-usage reading with a tiny claude -p call.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scheduled", action="store_true",
                      help="launchd entry point: read only if an automatic slot is due")
    mode.add_argument("--now", action="store_true", help="take a manual reading now")
    mode.add_argument("--status", action="store_true", help="print the meter state")
    args = parser.parse_args(argv)

    state_path = common.path("state", "meter.json")
    state = common.read_json(state_path, {}) or {}
    if args.status:
        reset = known_weekly_reset(state)
        state["known_weekly_reset_local"] = local(reset).isoformat() if reset else None
        print(json.dumps(state, indent=2))
        return 0

    lock = acquire_lock()
    if lock is None:
        return 0
    config = common.read_json(common.path("config.json"), {}) or {}
    if args.scheduled:
        due = due_run(common.now(), last_auto_slot(state), known_weekly_reset(state), interval_hours(config))
        if due is None:
            return 0
        trigger, slot = due
        # Record the slot before calling claude, so a failed run is never retried.
        state["last_auto_slot"], state["last_auto_day"] = slot, slot[:10]
        common.write_json_atomic(state_path, state)
    else:
        trigger = "manual"

    run, windows = take_reading(trigger, config)
    state["last_run"] = run
    seven_day = windows.get("seven_day") or {}
    if seven_day.get("resets_at"):
        state["weekly_reset"] = {"resets_at": seven_day["resets_at"], "seen_ts": run["ts"]}
    common.write_json_atomic(state_path, state)
    if args.scheduled:
        refresh_sessions()
    print(json.dumps(run))
    return 0 if run["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
