import json
import os
import subprocess
from datetime import date, timedelta

import pytest

import aggregate
from conftest import AGGREGATOR, SYSTEM_PYTHON, local_epoch

CONFIG = aggregate.load_config(os.devnull + "-missing")  # shipped defaults only
WEEK_A = 1791162000        # Sun 2026-10-04 21:00 EDT (the real weekly reset)
WEEK_B = WEEK_A + 7 * 86400
DAY_SHARE = 100 / 7


def r(when, week=None, five=None, week_reset=WEEK_A, five_reset=None, source="meter", **extra):
    """A reading at a local wall-clock time (needs the new_york fixture)."""
    ts = local_epoch(*when)
    record = {"ts": ts, "source": source,
              "seven_day": None if week is None else {"used_percentage": week, "resets_at": week_reset},
              "five_hour": None if five is None else {"used_percentage": five, "resets_at": five_reset}}
    record.update(extra)
    return record


def usage(readings):
    return {d.isoformat(): round(v, 4) for d, v in aggregate.weekly_usage_by_day(readings, CONFIG).items()}


def inputs(readings=(), activity=(), sessions=None, chats=None):
    return {"readings": sorted(readings, key=lambda x: x["ts"]), "activity": list(activity),
            "sessions": sessions or {}, "sessions_updated_at": None, "chats": chats or {}, "meter_state": {}}


SESSIONS = dict(CONFIG, level_source="sessions")  # the orange from session counts instead


def build(today, config=CONFIG, **kw):
    return aggregate.build(inputs(**kw), today, config, generated_at=0)


# --- plan usage ----------------------------------------------------------------------------

def test_first_reading_is_only_a_baseline(new_york):
    assert usage([r((2026, 9, 30, 11, 6), 8)]) == {}


def test_increases_are_summed_and_credited_to_the_later_readings_day(new_york):
    readings = [r((2026, 9, 30, 11, 0), 8), r((2026, 9, 30, 15, 0), 9.5),
                r((2026, 9, 30, 23, 55), 12), r((2026, 10, 1, 23, 55), 20)]
    assert usage(readings) == {"2026-09-30": 4.0, "2026-10-01": 8.0}


def test_readings_across_midnight_belong_to_the_later_day(new_york):
    readings = [r((2026, 9, 30, 23, 50), 10), r((2026, 10, 1, 0, 10), 12)]
    assert usage(readings) == {"2026-10-01": 2.0}


def test_weekly_reset_mid_day_counts_from_zero(new_york):
    readings = [r((2026, 10, 3, 23, 55), 40),
                r((2026, 10, 4, 20, 55), 45),                     # pre-reset reading
                r((2026, 10, 4, 22, 30), 2, week_reset=WEEK_B),   # after the 21:00 reset
                r((2026, 10, 4, 23, 55), 3, week_reset=WEEK_B)]
    assert usage(readings) == {"2026-10-04": 5 + 2 + 1}


def test_new_resets_at_is_a_reset_even_if_the_value_went_up(new_york):
    readings = [r((2026, 10, 4, 20, 55), 3), r((2026, 10, 5, 23, 55), 10, week_reset=WEEK_B)]
    assert usage(readings) == {"2026-10-05": 10.0}


def test_window_that_ended_between_readings_is_a_reset(new_york):
    readings = [r((2026, 10, 4, 20, 55), 30), r((2026, 10, 5, 12, 0), 4, week_reset=None)]
    assert usage(readings) == {"2026-10-05": 4.0}


def test_manual_limit_reset_sudden_drop(new_york):
    readings = [r((2026, 9, 30, 9, 0), 40), r((2026, 9, 30, 12, 0), 50),
                r((2026, 9, 30, 13, 0), 1),                       # limit reset early, same resets_at
                r((2026, 9, 30, 18, 0), 3)]
    assert usage(readings) == {"2026-09-30": 10 + 1 + 2}


def test_small_drops_between_sources_are_rounding_noise(new_york):
    readings = [r((2026, 9, 30, 9, 0), 12, source="statusline"), r((2026, 9, 30, 9, 5), 13.0),
                r((2026, 9, 30, 9, 10), 12, source="statusline"), r((2026, 9, 30, 9, 20), 13, source="statusline"),
                r((2026, 9, 30, 9, 30), 14, source="statusline")]
    assert usage(readings) == {"2026-09-30": 2.0}  # 12 -> 14, the dip is never counted twice


def test_resets_at_jitter_within_tolerance_is_not_a_reset(new_york):
    readings = [r((2026, 9, 30, 9, 0), 20), r((2026, 9, 30, 10, 0), 21, week_reset=WEEK_A + 30)]
    assert usage(readings) == {"2026-09-30": 1.0}


def test_missing_windows_are_skipped(new_york):
    readings = [r((2026, 9, 30, 9, 0), 20, five=5), r((2026, 9, 30, 10, 0), None, five=9),
                r((2026, 9, 30, 11, 0), 22, five=None)]
    assert usage(readings) == {"2026-09-30": 2.0}
    peaks = aggregate.five_hour_by_day(readings)
    assert peaks == {date(2026, 9, 30): (9.0, 2)}


def test_dst_fall_back_keeps_one_calendar_day(new_york):
    w4, w5 = WEEK_A + 4 * 604800, WEEK_A + 5 * 604800
    assert w4 == local_epoch(2026, 11, 1, 20, 0)  # fixed in UTC, so 20:00 EST after the change
    first_130 = local_epoch(2026, 11, 1, 1, 30)
    readings = [r((2026, 10, 31, 23, 59), 10, week_reset=w4),
                {"ts": first_130, "source": "meter", "seven_day": {"used_percentage": 11, "resets_at": w4}},
                {"ts": first_130 + 3600, "source": "meter",  # the repeated 01:30 hour
                 "seven_day": {"used_percentage": 12, "resets_at": w4}},
                r((2026, 11, 1, 19, 55), 15, week_reset=w4),   # pre-reset reading
                r((2026, 11, 1, 23, 55), 2, week_reset=w5)]    # after the 20:00 EST reset
    assert usage(readings) == {"2026-11-01": 1 + 1 + 3 + 2}


def test_dst_spring_forward(new_york):
    readings = [r((2026, 3, 8, 1, 59), 10, week_reset=None), r((2026, 3, 8, 3, 1), 11, week_reset=None),
                r((2026, 3, 9, 0, 1), 12, week_reset=None)]
    assert usage(readings) == {"2026-03-08": 1.0, "2026-03-09": 1.0}


@pytest.mark.parametrize("pp, sections", [
    (0, 0),                          # f = 0: empty battery
    (0.01, 1),                       # 0 < f <= 1/3
    (DAY_SHARE / 3, 1),
    (DAY_SHARE * 0.34, 2),           # 1/3 < f <= 2/3
    (DAY_SHARE * 2 / 3, 2),
    (DAY_SHARE * 0.67, 3),           # f > 2/3
    (DAY_SHARE, 3), (50, 3)])
def test_three_sections_from_usage(pp, sections):
    assert aggregate.usage_sections(pp, CONFIG) == sections


@pytest.mark.parametrize("sessions, sections", [(0, 0), (1, 1), (2, 2), (4, 2), (5, 3), (11, 3)])
def test_three_sections_from_sessions(sessions, sections):
    assert aggregate.session_sections(sessions, CONFIG["session_section_thresholds"]) == sections


def test_battery_fills_with_sessions(new_york):
    readings = [r((2026, 9, 29, 23, 55), 5), r((2026, 9, 30, 23, 55), 40)]  # a big usage day ...
    activity = [act((2026, 9, 30, 12, 0), "s%d" % i) for i in range(3)]  # ... with 3 sessions
    snapshot, details = build(date(2026, 9, 30), readings=readings, activity=activity)
    assert snapshot["battery"] == {"source": "sessions", "thresholds": [1, 4]}
    assert snapshot["afterburner"] == {"maxed_pct": 100, "other_pct": 10, "high_pct": 80, "next_pct": 21}
    assert snapshot["section_count"] == 3
    assert (snapshot["days"][-1]["sections"], details["days"]["2026-09-30"]["usage_pp"]) == (2, 35.0)


def test_usage_source_brings_back_the_weekly_share(new_york):
    readings = [r((2026, 9, 29, 23, 55), 5), r((2026, 9, 30, 23, 55), 40)]
    activity = [act((2026, 9, 30, 12, 0), "s%d" % i) for i in range(3)]
    usage_config = dict(CONFIG, section_source="usage")
    snapshot, _ = build(date(2026, 9, 30), usage_config, readings=readings, activity=activity)
    assert snapshot["battery"] == {"source": "usage", "thresholds": [0.3333333333, 0.6666666667]}
    assert snapshot["days"][-1]["sections"] == 3


def test_section_count_follows_the_config(new_york):
    snapshot, _ = build(date(2026, 9, 30))
    assert snapshot["section_count"] == 3
    four = dict(CONFIG, session_section_thresholds=[1, 2, 3])
    snapshot, _ = aggregate.build(inputs(), date(2026, 9, 30), four, generated_at=0)
    assert snapshot["section_count"] == 4
    four_usage = dict(CONFIG, section_source="usage", section_thresholds=[0.25, 0.5, 0.75])
    snapshot, _ = aggregate.build(inputs(), date(2026, 9, 30), four_usage, generated_at=0)
    assert snapshot["section_count"] == 4 and aggregate.usage_sections(50, four_usage) == 4


def test_days_before_tracking_still_fill_with_sessions(new_york):
    # First reading ever on Sep 28; Sep 29 is tracked but unused; Sep 30 has usage.
    readings = [r((2026, 9, 28, 23, 55), 5), r((2026, 9, 29, 23, 55), 5), r((2026, 9, 30, 23, 55), 7)]
    activity = [act((2026, 9, 27, 12, 0), "old")]  # a session before tracking started
    snapshot, _ = build(date(2026, 9, 30), readings=readings, activity=activity)
    by_date = {d["date"]: d for d in snapshot["days"]}
    assert [by_date["2026-09-27"][k] for k in ("usage_known", "sessions", "sections", "level")] == [False, 1, 1, 1]
    assert (by_date["2026-09-29"]["usage_known"], by_date["2026-09-29"]["sections"]) == (True, 0)   # empty battery
    assert (by_date["2026-09-30"]["usage_known"], by_date["2026-09-30"]["sections"]) == (True, 1)  # inferred session


# --- sessions ------------------------------------------------------------------------------

def act(when, sid, event="UserPromptSubmit", cwd="/p", entrypoint="claude-desktop", **extra):
    record = {"ts": local_epoch(*when), "event": event, "session_id": sid, "cwd": cwd, "entrypoint": entrypoint}
    record.update(extra)
    return record


def test_multi_day_session_counts_on_each_active_day(new_york):
    activity = [act((2026, 9, 28, 10, 0), "A"), act((2026, 9, 28, 16, 0), "A"),
                act((2026, 9, 30, 9, 0), "A"), act((2026, 9, 30, 9, 30), "B")]
    snapshot, details = build(date(2026, 9, 30), activity=activity)
    assert details["days"]["2026-09-28"]["sessions_code"] == 1
    assert "2026-09-29" not in details["days"]  # not active that day
    assert details["days"]["2026-09-30"]["sessions_code"] == 2
    a = details["days"]["2026-09-28"]["code_sessions"][0]
    assert a["first_ts"] == local_epoch(2026, 9, 28, 10, 0) and a["last_ts"] == local_epoch(2026, 9, 28, 16, 0)
    assert a["entrypoints"] == ["claude-desktop"]


def test_backfill_gives_start_and_last_days_before_hooks(new_york):
    sessions = {"S": {"session_id": "S", "title": "Old work", "cwd": "/old", "transcript_present": False,
                      "created_at": local_epoch(2026, 9, 1, 10, 0), "last_modified": local_epoch(2026, 9, 3, 18, 0)}}
    activity = [act((2026, 9, 30, 11, 7), "T")]
    _, details = build(date(2026, 9, 30), activity=activity, sessions=sessions)
    assert details["days"]["2026-09-01"]["code_sessions"][0]["title"] == "Old work"
    assert "2026-09-02" not in details["days"]  # the days in between are unknown
    assert details["days"]["2026-09-03"]["code_sessions"][0]["transcript_present"] is False


def test_backfill_is_ignored_once_hooks_are_running(new_york):
    sessions = {"S": {"session_id": "S", "title": "Live", "cwd": "/p", "transcript_present": True,
                      "created_at": local_epoch(2026, 9, 30, 9, 0), "last_modified": local_epoch(2026, 10, 2, 9, 0)}}
    activity = [act((2026, 9, 30, 11, 7), "S")]
    _, details = build(date(2026, 10, 2), activity=activity, sessions=sessions)
    assert sorted(details["days"]) == ["2026-09-30"]  # 10-02 came only from last_modified after hooks began
    assert details["days"]["2026-09-30"]["code_sessions"][0]["title"] == "Live"


def test_statusline_readings_mark_their_session_active(new_york):
    readings = [r((2026, 9, 30, 9, 0), 5, source="statusline", session_id="CLI", session_name="probe",
                  project_dir="/repo")]
    _, details = build(date(2026, 9, 30), readings=readings)
    [session] = details["days"]["2026-09-30"]["code_sessions"]
    assert (session["session_id"], session["title"], session["cwd"]) == ("CLI", "probe", "/repo")


def test_chats_and_code_sessions_are_split(new_york):
    chats = {"imported_through": "2026-09-30", "chats": {
        "c1": {"uuid": "c1", "title": "Essay help", "days": ["2026-09-29", "2026-09-30"]},
        "c2": {"uuid": "c2", "title": "Recipes", "days": ["2026-09-30"]},
        "bad": {"uuid": "bad", "days": ["not-a-date"]}}}
    _, details = build(date(2026, 9, 30), activity=[act((2026, 9, 30, 9, 0), "A")], chats=chats)
    today = details["days"]["2026-09-30"]
    assert (today["sessions"], today["sessions_code"], today["sessions_chat"]) == (3, 1, 2)
    assert [c["title"] for c in today["chats"]] == ["Essay help", "Recipes"]
    assert details["days"]["2026-09-29"]["sessions"] == 1
    assert details["status"]["chats_imported_through"] == "2026-09-30"
    assert details["status"]["chats_imported_at"] is None  # the fixture has no import time


def test_usage_without_a_known_session_counts_as_one(new_york):
    readings = [r((2026, 9, 29, 23, 55), 5), r((2026, 9, 30, 23, 55), 9)]
    _, details = build(date(2026, 9, 30), readings=readings)
    today = details["days"]["2026-09-30"]
    assert (today["sessions"], today["inferred_session"], today["level"]) == (1, True, 1)


# --- levels --------------------------------------------------------------------------------

def days_with(counts, end=date(2026, 9, 30)):
    """Activity giving day i (counting back from end) counts[i] distinct sessions."""
    activity = []
    for i, n in enumerate(counts):
        day = end - timedelta(days=i)
        for k in range(n):
            activity.append(act((day.year, day.month, day.day, 12, 0), "s-%d-%d" % (i, k)))
    return activity


@pytest.mark.parametrize("peak, used, level", [
    (73, 16, 3), (98, 24, 4), (52, 20, 3), (21, 5, 1), (25, 3, 1), (25.5, 3, 2), (75, 3, 3), (75.5, 3, 4),
    (2, 12, 1),       # a busy day whose only reading came after its 5-hour window reset
    (None, 3, 1),     # usage but no 5-hour reading: lightest orange
    (0, 3, 1),
    (0, 0, 0), (None, 0, 0),
])
def test_five_hour_level(peak, used, level):
    assert aggregate.five_hour_level(peak, used > 0, [25, 50, 75]) == level


def test_orange_follows_the_peak_five_hour(new_york):
    readings = [r((2026, 10, 9, 23, 55), 20, five=21), r((2026, 10, 10, 1, 45), 25, five=52),
                r((2026, 10, 10, 23, 55), 40, five=10)]
    activity = [act((2026, 10, 10, 12, 0), "s%d" % i) for i in range(9)]  # many sessions don't matter now
    snapshot, details = build(date(2026, 10, 10), readings=readings, activity=activity)
    today = details["days"]["2026-10-10"]
    assert (today["peak_five_hour_pct"], today["level"], today["sessions"]) == (52.0, 3, 9)
    assert snapshot["levels"] == {"mode": "five_hour", "thresholds": [25, 50, 75], "nonzero_days": 2}


def test_fixed_buckets_until_14_nonzero_days(new_york):
    counts = [1, 2, 3, 4, 6, 7, 12, 1, 1, 1, 1, 1, 1]  # 13 non-zero days
    _, details = build(date(2026, 9, 30), SESSIONS, activity=days_with(counts))
    assert details["levels"] == {"mode": "fixed", "thresholds": [1, 3, 6], "nonzero_days": 13}
    levels = [details["days"][(date(2026, 9, 30) - timedelta(days=i)).isoformat()]["level"] for i in range(7)]
    assert levels == [1, 2, 2, 3, 3, 4, 4]


def test_quartiles_once_there_are_14_nonzero_days(new_york):
    counts = [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 10]
    _, details = build(date(2026, 9, 30), SESSIONS, activity=days_with(counts))
    assert details["levels"]["mode"] == "quartiles"
    assert details["levels"]["thresholds"] == [2.25, 4.0, 5.75]
    by_count = {n: details["days"][(date(2026, 9, 30) - timedelta(days=i)).isoformat()]["level"]
                for i, n in enumerate(counts)}
    assert by_count == {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 8: 4, 10: 4}


def test_quartiles_never_collapse(new_york):
    # The real history on 2026-09-30: 31 one-session days, 6 two, 2 three, 1 ten.
    counts = [10] + [1] * 31 + [2] * 6 + [3] * 2
    _, details = build(date(2026, 9, 30), SESSIONS, activity=days_with(counts))
    assert details["levels"] == {"mode": "quartiles", "thresholds": [1.0, 2.0, 3.0], "nonzero_days": 40}
    by_count = {n: details["days"][(date(2026, 9, 30) - timedelta(days=i)).isoformat()]["level"]
                for i, n in enumerate(counts)}
    assert by_count == {1: 1, 2: 2, 3: 3, 10: 4}


def test_quartiles_only_use_the_trailing_365_days(new_york):
    old = days_with([9] * 20, end=date(2025, 9, 1))   # over a year before "today"
    recent = days_with([1] * 5)
    _, details = build(date(2026, 9, 30), SESSIONS, activity=old + recent)
    assert details["levels"]["mode"] == "fixed" and details["levels"]["nonzero_days"] == 5


# --- afterburner ---------------------------------------------------------------------------

def windows_of(*peaks):
    return [{"resets_at": 1000 + i * 18000, "peak_pct": p, "samples": 1} for i, p in enumerate(peaks)]


@pytest.mark.parametrize("peaks, expected", [
    ((100, 23), True),       # maxed out, then kept going in the next window
    ((23, 100), True),       # order doesn't matter
    ((100, 100), True),
    ((100, 10.5), True),
    ((100, 10), False),      # the other window must be over 10%
    ((100,), False),         # maxed out once and stopped
    ((60, 80, 40), False),
    ((), False),
    # over 80%, then a later window over 21%
    ((85, 30), True),
    ((99, 60), True),
    ((80.5, 21.5), True),
    ((80, 30), False),       # must be over 80%
    ((85, 21), False),       # the next must be over 21%
    ((30, 85), False),       # the high window has to come first
    ((85, 5, 30), True),     # a near-empty window in between doesn't break it
    ((10, 85, 22), True),
    ((98, 1, 8), False),     # Oct 11, 2026 at 9 PM ...
    ((98, 1, 90), True),     # ... and at midnight
])
def test_is_afterburner(peaks, expected):
    assert aggregate.is_afterburner(windows_of(*peaks), CONFIG) is expected


def test_five_hour_windows_are_grouped_by_reset(new_york):
    first, second = local_epoch(2026, 10, 10, 14, 0), local_epoch(2026, 10, 10, 20, 0)
    readings = [r((2026, 10, 10, 9, 55), 10, five=40, five_reset=first),
                r((2026, 10, 10, 12, 55), 20, five=100, five_reset=first + 30),   # jitter: same window
                r((2026, 10, 10, 15, 55), 22, five=12, five_reset=second),
                r((2026, 10, 10, 16, 55), 23, five=5, five_reset=None)]           # can't be placed
    windows = aggregate.five_hour_windows_by_day(readings, CONFIG)[date(2026, 10, 10)]
    assert windows == [{"resets_at": first, "peak_pct": 100.0, "samples": 2},
                       {"resets_at": second, "peak_pct": 12.0, "samples": 1}]


def test_afterburner_day(new_york):
    first, second = local_epoch(2026, 10, 10, 14, 0), local_epoch(2026, 10, 10, 20, 0)
    readings = [r((2026, 10, 9, 23, 55), 10, five=0, five_reset=first - 86400),
                r((2026, 10, 10, 12, 55), 20, five=100, five_reset=first),
                r((2026, 10, 10, 17, 55), 25, five=31, five_reset=second),
                r((2026, 10, 11, 9, 55), 26, five=100, five_reset=second + 86400)]  # maxed once, stopped
    snapshot, details = build(date(2026, 10, 11), readings=readings)
    by_date = {d["date"]: d for d in snapshot["days"]}
    assert (by_date["2026-10-10"]["afterburner"], by_date["2026-10-11"]["afterburner"]) == (True, False)
    assert details["days"]["2026-10-10"]["afterburner"] is True
    assert [w["peak_pct"] for w in details["days"]["2026-10-10"]["five_hour_windows"]] == [100.0, 31.0]
    assert by_date["2026-10-09"]["afterburner"] is False


# --- grid and outputs ----------------------------------------------------------------------

def test_empty_history(new_york):
    snapshot, details = build(date(2026, 9, 30))
    assert details["days"] == {}
    assert snapshot["levels"] == {"mode": "five_hour", "thresholds": [25, 50, 75], "nonzero_days": 0}
    assert all(d["sections"] == 0 and d["level"] == 0 and not d["usage_known"] for d in snapshot["days"])
    assert snapshot["header"] == {"week": None, "five_hour": None, "today_usage_pp": 0, "today_sessions": 0}
    assert snapshot["usage_tracked_since"] is None


def test_grid_starts_on_sunday_53_weeks_back_and_hides_future_days(new_york):
    snapshot, _ = build(date(2026, 9, 30))  # a Wednesday
    days = [date.fromisoformat(d["date"]) for d in snapshot["days"]]
    assert days[0] == date(2025, 9, 28) and days[0].weekday() == 6  # Sunday, 52 weeks before this one
    assert days[-1] == date(2026, 9, 30)
    assert len(days) == 52 * 7 + 4
    assert all(b - a == timedelta(days=1) for a, b in zip(days, days[1:]))


def test_grid_is_continuous_across_dst(new_york):
    snapshot, _ = build(date(2026, 11, 8))
    days = [date.fromisoformat(d["date"]) for d in snapshot["days"]]
    assert len(set(days)) == len(days)
    assert all(b - a == timedelta(days=1) for a, b in zip(days, days[1:]))


def test_header_and_usage_known(new_york):
    readings = [r((2026, 9, 30, 11, 6), 8, five=6, five_reset=1790798400),
                r((2026, 9, 30, 23, 55), 11, five=20, five_reset=1790798400)]
    snapshot, _ = build(date(2026, 9, 30), readings=readings)
    assert snapshot["header"]["week"] == {"used_pct": 11, "resets_at": WEEK_A,
                                          "as_of": local_epoch(2026, 9, 30, 23, 55), "source": "meter"}
    assert snapshot["header"]["today_usage_pp"] == 3.0
    assert snapshot["usage_tracked_since"] == "2026-09-30"
    assert [d["usage_known"] for d in snapshot["days"][-2:]] == [False, True]
    assert snapshot["days"][-1] == {"date": "2026-09-30", "usage_pp": 3.0, "sections": 1, "sessions": 1,
                                    "level": 1, "afterburner": False, "usage_known": True}


@pytest.mark.parametrize("through, days_since, remind", [
    (None, None, True),                 # never imported
    ("2026-09-30", 0, False),
    ("2026-09-23", 7, False),           # exactly a week: not yet
    ("2026-09-22", 8, True),
    ("garbage", None, True),
])
def test_chat_import_reminder(new_york, through, days_since, remind):
    chats = {"imported_through": through, "chats": {}} if through else None
    snapshot, _ = build(date(2026, 9, 30), chats=chats)
    assert snapshot["chats"] == {"imported_through": through, "days_since": days_since, "remind": remind}


def test_user_config_overrides_thresholds(grid_home):
    grid_home.mkdir(parents=True)
    (grid_home / "aggregator-config.json").write_text(json.dumps({"section_thresholds": [0.1, 0.2, 0.3]}))
    config = aggregate.load_config()
    assert config["section_thresholds"] == [0.1, 0.2, 0.3] and config["grid_weeks"] == 53
    assert aggregate.usage_sections(DAY_SHARE * 0.25, config) == 3


def test_cli_writes_outputs_and_skips_malformed_lines(grid_home):
    grid_home.mkdir(parents=True)
    (grid_home / "readings.jsonl").write_text(
        'not json\n{"ts": "bad"}\n'
        '{"ts": 1790780781.9, "source": "meter", "seven_day": {"used_percentage": 8, "resets_at": 1791162000}}\n')
    (grid_home / "activity.jsonl").write_text(
        '{"ts": 1790780831.1, "event": "UserPromptSubmit", "session_id": "762e", "cwd": "/p", "entrypoint": "claude-desktop"}\n')
    result = subprocess.run([SYSTEM_PYTHON, os.path.join(AGGREGATOR, "aggregate.py"), "--today", "2026-09-30"],
                            env=dict(os.environ, TZ="America/New_York"), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode()
    snapshot = json.loads((grid_home / "out" / "snapshot.json").read_text())
    details = json.loads((grid_home / "out" / "details.json").read_text())
    assert snapshot["days"][-1]["sessions"] == 1
    assert details["status"]["last_reading"]["source"] == "meter"
    assert details["status"]["hooks_first_ts"] == 1790780831.1
