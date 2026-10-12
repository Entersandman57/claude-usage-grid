#!/usr/bin/env python3
"""Turn the collectors' logs into the grid's day data.

Reads from ~/.claude-usage-grid: readings.jsonl, activity.jsonl, sessions.json,
chats.json, state/meter.json and state/statusline.json. Writes out/snapshot.json
(what the widget draws) and out/details.json (tooltips, day view, status panel).

Day boundaries use the Mac's local time zone and weeks start on Sunday.
Thresholds live in aggregator-config.json; a copy in the data directory
overrides the shipped defaults key by key.
Stdlib only, Python 3.9 compatible.
"""
import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # installed: common.py sits beside this file
sys.path.insert(1, os.path.join(os.path.dirname(HERE), "collectors"))  # repo layout
import common  # noqa: E402

SNAPSHOT_VERSION = 3  # 2: battery sections replaced bars; 3: sections from sessions, afterburner
CONFIG_NAME = "aggregator-config.json"
EPSILON = 1e-9


# --- inputs --------------------------------------------------------------------------------

def load_config(override_path=None):
    with open(os.path.join(HERE, CONFIG_NAME), encoding="utf-8") as f:
        config = json.load(f)
    user_path = override_path or common.path(CONFIG_NAME)
    if os.path.exists(user_path):
        with open(user_path, encoding="utf-8") as f:
            config.update(json.load(f))
    return config


def read_jsonl(file_path):
    """Records with a numeric ts; malformed lines are skipped."""
    records = []
    try:
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and common.is_number(record.get("ts")):
                    records.append(record)
    except OSError:
        pass
    return records


def load_inputs():
    sessions = common.read_json(common.path("sessions.json"), {}) or {}
    return {
        "readings": sorted(read_jsonl(common.path("readings.jsonl")), key=lambda r: r["ts"]),
        "activity": read_jsonl(common.path("activity.jsonl")),
        "sessions": sessions.get("sessions") or {},
        "sessions_updated_at": sessions.get("updated_at"),
        "chats": common.read_json(common.path("chats.json"), {}) or {},
        "meter_state": common.read_json(common.path("state", "meter.json"), {}) or {},
    }


def day_of(ts):
    return datetime.fromtimestamp(ts).date()


# --- plan usage ----------------------------------------------------------------------------

def weekly_usage_by_day(readings, config):
    """Percentage points of the weekly limit used per local day.

    Walks the readings in time order and sums the increases of
    seven_day.used_percentage, crediting each increase to the day of the later
    reading. A window reset (a new resets_at, the previous window having ended,
    or a drop of at least reset_drop_threshold_pp) restarts from 0, so the new
    reading's whole value counts. Smaller drops are rounding differences between
    the status line and the meter: the high-water mark is kept, so the same
    points are never counted twice and usage is never negative.
    """
    tolerance = config["resets_at_tolerance_seconds"]
    drop_threshold = config["reset_drop_threshold_pp"]
    usage = defaultdict(float)
    high = window_end = None
    for reading in sorted(readings, key=lambda r: r["ts"]):
        window = common.normalize_window(reading.get("seven_day"))
        if window is None:
            continue
        pct, resets_at = float(window["used_percentage"]), window["resets_at"]
        if high is None:  # the first reading is only a baseline
            high, window_end = pct, resets_at
            continue
        is_reset = window_end is not None and (
            (resets_at is not None and abs(resets_at - window_end) > tolerance)
            or reading["ts"] > window_end)
        if is_reset or high - pct >= drop_threshold:
            gained, high = pct, pct
        else:
            gained, high = max(0.0, pct - high), max(high, pct)
        if gained > EPSILON:
            usage[day_of(reading["ts"])] += gained
        if resets_at is not None:
            window_end = resets_at
    return dict(usage)


def five_hour_by_day(readings):
    """{day: (highest five_hour % seen that day, number of readings)}."""
    peaks = {}
    for reading in readings:
        window = common.normalize_window(reading.get("five_hour"))
        if window is None:
            continue
        day = day_of(reading["ts"])
        peak, samples = peaks.get(day, (None, 0))
        pct = float(window["used_percentage"])
        peaks[day] = (pct if peak is None else max(peak, pct), samples + 1)
    return peaks


def five_hour_windows_by_day(readings, config):
    """{day: [{"resets_at", "peak_pct", "samples"}]}: each 5-hour window read that
    day, with its highest reading. Readings belong to the same window when their
    resets_at agree within resets_at_tolerance_seconds; a reading without a
    resets_at can't be placed and is left out (it still counts for the peak)."""
    tolerance = config["resets_at_tolerance_seconds"]
    days = defaultdict(list)
    for reading in readings:
        window = common.normalize_window(reading.get("five_hour"))
        if window is None or window["resets_at"] is None:
            continue
        pct, resets_at = float(window["used_percentage"]), window["resets_at"]
        windows = days[day_of(reading["ts"])]
        match = next((w for w in windows if abs(w["resets_at"] - resets_at) <= tolerance), None)
        if match is None:
            windows.append({"resets_at": resets_at, "peak_pct": pct, "samples": 1})
        else:
            match["peak_pct"], match["samples"] = max(match["peak_pct"], pct), match["samples"] + 1
    return dict(days)


def is_afterburner(windows, config):
    """True if the day's 5-hour windows show you working past a near-limit window:
      * one hit its limit (afterburner_maxed_pct) and another went over
        afterburner_other_pct (either order), or
      * one went over afterburner_high_pct and a later window that day went
        over afterburner_next_pct. Any later window counts, so a near-empty
        window in between (one a meter call started, say) doesn't break it."""
    maxed = [w for w in windows if w["peak_pct"] >= config["afterburner_maxed_pct"] - EPSILON]
    if any(other is not window and other["peak_pct"] > config["afterburner_other_pct"]
           for window in maxed for other in windows):
        return True
    ordered = sorted(windows, key=lambda w: w["resets_at"])
    return any(window["peak_pct"] > config["afterburner_high_pct"]
               and any(later["peak_pct"] > config["afterburner_next_pct"] for later in ordered[i + 1:])
               for i, window in enumerate(ordered))


def battery_thresholds(config):
    """(section_source, thresholds): what fills a cell's battery sections."""
    if config["section_source"] == "usage":
        return "usage", list(config["section_thresholds"])
    return "sessions", list(config["session_section_thresholds"])


def session_sections(sessions, thresholds):
    """Sections filled by the day's session count. With the default thresholds
    [1, 4]: 0 sessions -> 0, 1 -> 1, 2-4 -> 2, 5 or more -> 3."""
    return level_for(sessions, thresholds)


def usage_sections(usage_pp, config):
    """How many of the cell's battery sections are filled (0 to len(section_thresholds) + 1)
    when section_source is "usage".

    f = the day's usage / an even daily share of the week (100 / days_per_week).
    f = 0 fills none; otherwise the first threshold that f doesn't exceed decides.
    With the default thresholds [1/3, 2/3]: f <= 1/3 -> 1, <= 2/3 -> 2, above -> 3.
    """
    if usage_pp <= EPSILON:
        return 0
    fraction = usage_pp / (100.0 / config["days_per_week"])
    for sections, threshold in enumerate(config["section_thresholds"], start=1):
        if fraction <= threshold + EPSILON:
            return sections
    return len(config["section_thresholds"]) + 1


# --- sessions ------------------------------------------------------------------------------

def code_sessions_by_day(activity, readings, sessions):
    """{day: {session_id: info}} for Claude Code sessions active that day.

    Hook events and status-line readings give exact days. The list_sessions()
    backfill only knows each session's start and last change, so it is used
    only for moments before the hooks' first event.
    """
    days = defaultdict(dict)

    def touch(sid, ts, cwd=None, entrypoint=None, title=None):
        info = days[day_of(ts)].setdefault(sid, {
            "session_id": sid, "title": None, "cwd": None,
            "first_ts": ts, "last_ts": ts, "entrypoints": set()})
        info["first_ts"], info["last_ts"] = min(info["first_ts"], ts), max(info["last_ts"], ts)
        info["cwd"] = info["cwd"] or cwd
        info["title"] = info["title"] or title
        if entrypoint:
            info["entrypoints"].add(entrypoint)

    for record in activity:
        if record.get("session_id"):
            touch(record["session_id"], record["ts"], record.get("cwd"),
                  record.get("entrypoint"), record.get("title"))
    for reading in readings:
        if reading.get("source") == "statusline" and reading.get("session_id"):
            touch(reading["session_id"], reading["ts"], reading.get("project_dir"),
                  title=reading.get("session_name"))
    hooks_start = min((r["ts"] for r in activity), default=None)
    for session in sessions.values():
        for key in ("created_at", "last_modified"):
            ts = session.get(key)
            if common.is_number(ts) and (hooks_start is None or ts < hooks_start):
                touch(session["session_id"], ts, session.get("cwd"))

    for by_session in days.values():
        for sid, info in by_session.items():
            meta = sessions.get(sid) or {}
            info["title"] = meta.get("title") or info["title"]
            info["cwd"] = info["cwd"] or meta.get("cwd")
            info["transcript_present"] = meta.get("transcript_present")  # None: not backfilled yet
            info["entrypoints"] = sorted(info["entrypoints"])
    return days


def chats_by_day(chats):
    """{day: {uuid: {"uuid", "title"}}} from the claude.ai export import."""
    days = defaultdict(dict)
    for chat in (chats.get("chats") or {}).values():
        if not isinstance(chat, dict) or not chat.get("uuid"):
            continue
        for day in chat.get("days") or []:
            try:
                parsed = date.fromisoformat(day)
            except (TypeError, ValueError):
                continue
            days[parsed][chat["uuid"]] = {"uuid": chat["uuid"], "title": chat.get("title")}
    return days


# --- levels --------------------------------------------------------------------------------

def level_thresholds(totals, today, config):
    """("fixed" | "quartiles", [t1, t2, t3], non-zero days in the window).

    Levels are relative to your history: quartiles of the non-zero session days
    in the trailing level_window_days (all history if shorter). Until there are
    quartile_min_days such days, fixed buckets are used (1 / 2-3 / 4-6 / 7+).
    Each threshold is at least one session above the previous one, so a history
    of mostly 1-session days can't collapse the levels (quartiles 1, 1, 1 would
    make a 2-session day level 4; they become 1, 2, 3).
    """
    start = today - timedelta(days=config["level_window_days"] - 1)
    nonzero = [n for day, n in totals.items() if start <= day <= today and n > 0]
    if len(nonzero) < config["quartile_min_days"]:
        return "fixed", list(config["fixed_level_thresholds"]), len(nonzero)
    thresholds = []
    for quartile in statistics.quantiles(nonzero, n=4, method="inclusive"):
        thresholds.append(max(quartile, thresholds[-1] + 1) if thresholds else quartile)
    return "quartiles", [round(t, 4) for t in thresholds], len(nonzero)


def level_for(value, thresholds):
    """0 for nothing, else 1 + how many thresholds the value exceeds."""
    if value <= 0:
        return 0
    for level, threshold in enumerate(thresholds, start=1):
        if value <= threshold:
            return level
    return len(thresholds) + 1


def five_hour_level(peak, active, thresholds):
    """Orange from the day's peak 5-hour %: fixed quarters of the 5-hour limit
    (with the default thresholds, <=25% is 1, <=50% 2, <=75% 3, above 4). An
    active day (usage or sessions) with no 5-hour reading above 0, such as a day
    before tracking started, is level 1, so its sections get the lightest orange."""
    if peak is not None and peak > 0:
        return level_for(peak, thresholds)
    return 1 if active else 0


# --- output --------------------------------------------------------------------------------

def sunday_on_or_before(day):
    return day - timedelta(days=(day.weekday() + 1) % 7)


def latest_window(readings, name):
    for reading in reversed(readings):
        window = common.normalize_window(reading.get(name))
        if window:
            return {"used_pct": window["used_percentage"], "resets_at": window["resets_at"],
                    "as_of": reading["ts"], "source": reading.get("source")}
    return None


def chat_import_status(chats, today, config):
    """How current the claude.ai import is. Chats after imported_through aren't
    counted, so once it's more than chat_reminder_days old (or there's never been
    an import) the widget and app remind you to import a newer export."""
    through = chats.get("imported_through")
    try:
        days_since = (today - date.fromisoformat(through)).days if through else None
    except ValueError:
        days_since = None
    return {"imported_through": through, "days_since": days_since,
            "remind": days_since is None or days_since > config["chat_reminder_days"]}


def build(inputs, today, config, generated_at):
    readings = inputs["readings"]
    usage = {d: u for d, u in weekly_usage_by_day(readings, config).items() if d <= today}
    five_hour = five_hour_by_day(readings)
    windows = five_hour_windows_by_day(readings, config)
    code = code_sessions_by_day(inputs["activity"], readings, inputs["sessions"])
    chats = chats_by_day(inputs["chats"])

    active_days = sorted(d for d in set(usage) | set(five_hour) | set(code) | set(chats) if d <= today)
    section_source, section_thresholds = battery_thresholds(config)
    totals, detail_days = {}, {}
    for day in active_days:
        used = usage.get(day, 0.0)
        n_code, n_chat = len(code.get(day, {})), len(chats.get(day, {}))
        inferred = used > EPSILON and n_code + n_chat == 0
        totals[day] = 1 if inferred else n_code + n_chat
        peak, samples = five_hour.get(day, (None, 0))
        day_windows = windows.get(day, [])
        detail_days[day] = {
            "usage_pp": round(used, 2),
            "share_fraction": round(used / (100.0 / config["days_per_week"]), 3),
            "sections": (usage_sections(used, config) if section_source == "usage"
                         else session_sections(totals[day], section_thresholds)),
            "peak_five_hour_pct": peak, "five_hour_samples": samples,
            "five_hour_windows": day_windows, "afterburner": is_afterburner(day_windows, config),
            "sessions": totals[day], "sessions_code": n_code, "sessions_chat": n_chat,
            "inferred_session": inferred,
            "code_sessions": sorted(code.get(day, {}).values(), key=lambda s: s["first_ts"]),
            "chats": sorted(chats.get(day, {}).values(), key=lambda c: c["title"] or ""),
        }

    # level_source decides the orange: "five_hour" (the day's peak 5-hour %) or
    # "sessions" (session counts, ranked against your history).
    if config["level_source"] == "five_hour":
        thresholds = list(config["five_hour_level_thresholds"])
        mode = "five_hour"
        nonzero_days = sum(1 for detail in detail_days.values() if (detail["peak_five_hour_pct"] or 0) > 0)
        for detail in detail_days.values():
            active = detail["usage_pp"] > EPSILON or detail["sessions"] > 0
            detail["level"] = five_hour_level(detail["peak_five_hour_pct"], active, thresholds)
    else:
        mode, thresholds, nonzero_days = level_thresholds(totals, today, config)
        for detail in detail_days.values():
            detail["level"] = level_for(detail["sessions"], thresholds)

    # Days before the first weekly reading ever recorded have no usage data
    # (usage_known false). Their batteries still fill with sessions, and the
    # tooltips and day view say "no usage data".
    first_reading = next((r["ts"] for r in readings if common.normalize_window(r.get("seven_day"))), None)
    usage_since = day_of(first_reading) if first_reading is not None else None
    grid_start = sunday_on_or_before(today) - timedelta(weeks=config["grid_weeks"] - 1)
    grid = []
    day = grid_start
    while day <= today:
        detail = detail_days.get(day)
        grid.append({
            "date": day.isoformat(),
            "usage_pp": detail["usage_pp"] if detail else 0,
            "sections": detail["sections"] if detail else 0,
            "sessions": detail["sessions"] if detail else 0,
            "level": detail["level"] if detail else 0,
            "afterburner": detail["afterburner"] if detail else False,
            "usage_known": usage_since is not None and day >= usage_since,
        })
        day += timedelta(days=1)

    today_detail = detail_days.get(today) or {}
    header = {
        "week": latest_window(readings, "seven_day"),
        "five_hour": latest_window(readings, "five_hour"),
        "today_usage_pp": today_detail.get("usage_pp", 0),
        "today_sessions": today_detail.get("sessions", 0),
    }
    levels = {"mode": mode, "thresholds": thresholds, "nonzero_days": nonzero_days}
    snapshot = {
        "version": SNAPSHOT_VERSION, "generated_at": generated_at, "today": today.isoformat(),
        "week_start": "sunday", "usage_tracked_since": usage_since.isoformat() if usage_since else None,
        "section_count": len(section_thresholds) + 1,
        "battery": {"source": section_source, "thresholds": section_thresholds},
        "afterburner": {"maxed_pct": config["afterburner_maxed_pct"], "other_pct": config["afterburner_other_pct"],
                        "high_pct": config["afterburner_high_pct"], "next_pct": config["afterburner_next_pct"]},
        "chats": chat_import_status(inputs["chats"], today, config),
        "header": header, "levels": levels, "days": grid,
    }

    statusline_ts = [r["ts"] for r in readings if r.get("source") == "statusline"]
    meter_state = inputs["meter_state"]
    details = {
        "version": SNAPSHOT_VERSION, "generated_at": generated_at, "today": today.isoformat(),
        "levels": levels, "header": header,
        "days": {d.isoformat(): v for d, v in detail_days.items()},
        "status": {
            "last_reading": ({"ts": readings[-1]["ts"], "source": readings[-1].get("source")}
                             if readings else None),
            "statusline_last_ts": max(statusline_ts) if statusline_ts else None,
            "meter_last_run": meter_state.get("last_run"),
            "meter_last_auto_day": meter_state.get("last_auto_day"),
            "sessions_updated_at": inputs["sessions_updated_at"],
            "hooks_first_ts": min((r["ts"] for r in inputs["activity"]), default=None),
            "chats_imported_through": inputs["chats"].get("imported_through"),
            "chats_imported_at": inputs["chats"].get("imported_at"),
        },
    }
    return snapshot, details


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate usage logs into snapshot.json and details.json.")
    parser.add_argument("--today", type=date.fromisoformat, help="pretend today is YYYY-MM-DD (testing)")
    parser.add_argument("--out", help="output directory (default: <data dir>/out)")
    parser.add_argument("--config", help="config file overriding the shipped defaults")
    args = parser.parse_args(argv)

    generated_at = round(common.now(), 3)
    today = args.today or day_of(generated_at)
    snapshot, details = build(load_inputs(), today, load_config(args.config), generated_at)
    out_dir = args.out or common.path("out")
    common.write_json_atomic(os.path.join(out_dir, "details.json"), details)
    common.write_json_atomic(os.path.join(out_dir, "snapshot.json"), snapshot)
    print("%s: %d grid days, %d active, levels %s %s" % (
        out_dir, len(snapshot["days"]), len(details["days"]), details["levels"]["mode"],
        details["levels"]["thresholds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
