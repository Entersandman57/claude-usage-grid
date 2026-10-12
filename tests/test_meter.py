import json
import os
import stat

import pytest

import meter
from conftest import SYSTEM_PYTHON, all_text, fixture_path, local_epoch, read_fixture, run_collector

REAL_WEEKLY_RESET = 1791162000  # Sun 2026-10-04 21:00 EDT, from the Phase 0 probe


# --- parsing -------------------------------------------------------------------------------

def test_parses_both_windows_from_real_event():
    windows, status, error, cost = meter.parse_stream(read_fixture("meter_stream_ok.jsonl"))
    assert windows == {
        "five_hour": {"used_percentage": 13.0, "resets_at": 1790771400},
        "seven_day": {"used_percentage": 5.0, "resets_at": 1791162000},
    }
    assert (status, error, cost) == ("allowed", None, 0.000676)


def test_falls_back_to_documented_top_level_fields():
    windows, status, _, _ = meter.parse_stream(read_fixture("meter_stream_top_level_only.jsonl"))
    assert windows == {"seven_day": {"used_percentage": 42.0, "resets_at": 1791162000}}
    assert status == "allowed_warning"


def test_not_logged_in_is_an_error_without_windows():
    windows, _, error, _ = meter.parse_stream(read_fixture("meter_stream_not_logged_in.jsonl"))
    assert windows == {}
    assert error == "Not logged in · Please run /login"


@pytest.mark.parametrize("info", [
    None, "x", {}, {"unifiedWindows": "x"},
    {"unifiedWindows": {"seven_day": {"utilization": "0.4"}}},
    {"rateLimitType": "overage", "utilization": 0.5},
    {"rateLimitType": "seven_day"},
])
def test_ignores_unusable_rate_limit_info(info):
    assert meter.parse_rate_limit_info(info) == {}


def test_full_utilization_is_100_percent():
    info = {"unifiedWindows": {"seven_day": {"utilization": 1.0, "resetsAt": 1}}}
    assert meter.parse_rate_limit_info(info)["seven_day"]["used_percentage"] == 100.0


# --- schedule ------------------------------------------------------------------------------

def test_rejected_window_without_utilization_is_at_its_limit():
    info = {"status": "rejected", "rateLimitType": "five_hour", "resetsAt": 7}
    assert meter.parse_rate_limit_info(info) == {"five_hour": {"used_percentage": 100.0, "resets_at": 7}}


# --- schedule ------------------------------------------------------------------------------

def test_slots_every_three_hours_ending_at_2355():
    from datetime import date
    hours = [slot.hour for slot in meter.regular_slots(date(2026, 9, 30), 3)]
    assert hours == [2, 5, 8, 11, 14, 17, 20, 23]
    assert all(slot.minute == 55 for slot in meter.regular_slots(date(2026, 9, 30), 3))
    assert [slot.hour for slot in meter.regular_slots(date(2026, 9, 30), 24)] == [23]  # once a day
    assert [slot.hour for slot in meter.regular_slots(date(2026, 9, 30), 5)] == [3, 8, 13, 18, 23]


@pytest.mark.parametrize("config, hours", [
    ({}, 3), ({"meter_interval_hours": 6}, 6), ({"meter_interval_hours": 24}, 24),
    ({"meter_interval_hours": 0}, 3), ({"meter_interval_hours": 25}, 3),
    ({"meter_interval_hours": "2"}, 3), ({"meter_interval_hours": True}, 3),
])
def test_interval_hours(config, hours):
    assert meter.interval_hours(config) == hours


@pytest.mark.parametrize("when, last_slot, expected", [
    ((2026, 9, 30, 0, 55), None, None),                                   # before the day's first slot
    ((2026, 9, 30, 1, 55), None, None),
    ((2026, 9, 30, 2, 55), None, ("scheduled", "2026-09-30T02:55")),
    ((2026, 9, 30, 2, 54, 40), None, ("scheduled", "2026-09-30T02:55")),  # launchd a few seconds early
    ((2026, 9, 30, 3, 55), "2026-09-30T02:55", None),                     # that slot already ran
    ((2026, 9, 30, 12, 0), "2026-09-30T08:55", ("scheduled", "2026-09-30T11:55")),
    ((2026, 9, 30, 13, 55), "2026-09-30T08:55", ("scheduled", "2026-09-30T11:55")),  # woke late: catch up
    ((2026, 9, 30, 14, 55), "2026-09-30T08:55", ("scheduled", "2026-09-30T14:55")),  # only the latest slot
    ((2026, 9, 30, 23, 55), "2026-09-30T20:55", ("scheduled", "2026-09-30T23:55")),
    ((2026, 10, 1, 0, 55), "2026-09-29T23:55", None),                     # missed 23:55: no catch-up after midnight
    ((2026, 10, 4, 19, 55), "2026-10-04T17:55", None),                    # reset day
    ((2026, 10, 4, 20, 55), "2026-10-04T17:55", ("pre_reset", "2026-10-04T20:55")),  # last :55 before 21:00
    ((2026, 10, 4, 20, 59, 30), "2026-10-04T17:55", ("scheduled", "2026-10-04T20:55")),  # too close to the reset
    ((2026, 10, 4, 21, 55), "2026-10-04T20:55", None),                    # pre-reset run counts as that slot
    ((2026, 10, 4, 23, 55), "2026-10-04T20:55", ("scheduled", "2026-10-04T23:55")),
    ((2026, 10, 11, 20, 55), None, ("pre_reset", "2026-10-11T20:55")),    # next week, projected from the known reset
    ((2026, 11, 1, 19, 55), "2026-11-01T17:55", ("pre_reset", "2026-11-01T19:55")),  # DST ended: reset is 20:00 EST
    ((2026, 11, 1, 20, 55), "2026-11-01T19:55", ("scheduled", "2026-11-01T20:55")),
])
def test_due_run(new_york, when, last_slot, expected):
    assert local_epoch(2026, 10, 4, 21, 0) == REAL_WEEKLY_RESET
    assert meter.due_run(local_epoch(*when), last_slot, REAL_WEEKLY_RESET) == expected


def test_pre_reset_slot_between_regular_slots(new_york):
    reset = local_epoch(2026, 10, 7, 22, 30)
    assert meter.due_run(local_epoch(2026, 10, 7, 21, 55), "2026-10-07T20:55", reset) == (
        "pre_reset", "2026-10-07T21:55")
    assert meter.due_run(local_epoch(2026, 10, 7, 22, 55), "2026-10-07T21:55", reset) is None
    assert meter.due_run(local_epoch(2026, 10, 7, 23, 55), "2026-10-07T21:55", reset) == (
        "scheduled", "2026-10-07T23:55")


def test_reset_just_after_midnight_uses_normal_slots(new_york):
    reset = local_epoch(2026, 10, 5, 0, 30)
    assert meter.due_run(local_epoch(2026, 10, 4, 23, 55), None, reset) == ("scheduled", "2026-10-04T23:55")
    assert meter.due_run(local_epoch(2026, 10, 5, 0, 20), "2026-10-04T23:55", reset) is None


def test_unknown_reset_means_regular_slots_only(new_york):
    assert meter.due_run(local_epoch(2026, 10, 4, 21, 55), "2026-10-04T20:55", None) is None
    assert meter.due_run(local_epoch(2026, 10, 4, 23, 55), "2026-10-04T20:55", None) == (
        "scheduled", "2026-10-04T23:55")


def test_once_a_day_interval_matches_the_old_schedule(new_york):
    assert meter.due_run(local_epoch(2026, 9, 30, 20, 55), None, None, interval=24) is None
    assert meter.due_run(local_epoch(2026, 9, 30, 23, 55), None, None, interval=24) == (
        "scheduled", "2026-09-30T23:55")


def test_state_from_the_once_a_day_meter_counts_its_last_run(new_york):
    state = {"last_auto_day": "2026-10-11",
             "last_run": {"ts": local_epoch(2026, 10, 11, 20, 55, 8), "trigger": "pre_reset"}}
    assert meter.last_auto_slot(state) == "2026-10-11T20:55"
    assert meter.due_run(local_epoch(2026, 10, 11, 22, 55), meter.last_auto_slot(state), None) is None
    assert meter.last_auto_slot({"last_run": {"ts": 1, "trigger": "manual"}}) is None
    assert meter.last_auto_slot(dict(state, last_auto_slot="2026-10-11T23:55")) == "2026-10-11T23:55"


def test_status_line_supplies_the_reset_when_newer(grid_home):
    (grid_home / "state").mkdir(parents=True)
    (grid_home / "state" / "statusline.json").write_text(json.dumps(
        {"ts": 200, "windows": {"seven_day": {"used_percentage": 5, "resets_at": 999}}}))
    assert meter.known_weekly_reset({"weekly_reset": {"resets_at": 111, "seen_ts": 100}}) == 999
    assert meter.known_weekly_reset({"weekly_reset": {"resets_at": 111, "seen_ts": 300}}) == 111


# --- running claude (with a fake binary) ---------------------------------------------------

@pytest.fixture
def fake_claude(grid_home, tmp_path):
    """Install a fake `claude` that replays a fixture stream and records how it was called."""
    calls = tmp_path / "calls.jsonl"

    def install(stream_fixture, exit_code=0, sleep=0, timeout=None):
        script = tmp_path / "claude"
        script.write_text(
            "#!%s\nimport json, os, sys, time\n"
            "open(%r, 'a').write(json.dumps({'argv': sys.argv[1:], 'env': dict(os.environ), 'cwd': os.getcwd()}) + '\\n')\n"
            "time.sleep(%r)\nsys.stdout.write(open(%r).read())\nsys.exit(%d)\n"
            % (SYSTEM_PYTHON, str(calls), sleep, fixture_path(stream_fixture), exit_code))
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        grid_home.mkdir(parents=True, exist_ok=True)
        config = {"claude_bin": str(script)}
        if timeout:
            config["meter_timeout_seconds"] = timeout
        (grid_home / "config.json").write_text(json.dumps(config))

    def recorded():
        return [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    install.calls = recorded
    return install


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_manual_reading_logs_both_windows(grid_home, fake_claude, monkeypatch):
    fake_claude("meter_stream_ok.jsonl")
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", "1790755500")
    assert meter.main(["--now"]) == 0

    [reading] = jsonl(grid_home / "readings.jsonl")
    assert reading == {
        "ts": 1790755500, "source": "meter", "trigger": "manual",
        "session_id": None, "session_name": None, "project_dir": None,
        "five_hour": {"used_percentage": 13.0, "resets_at": 1790771400},
        "seven_day": {"used_percentage": 5.0, "resets_at": 1791162000},
        "status": "allowed",
    }
    [run] = jsonl(grid_home / "meter-runs.jsonl")
    assert run["ok"] and run["windows"] == ["five_hour", "seven_day"] and run["cost_usd"] == 0.000676
    state = json.loads((grid_home / "state" / "meter.json").read_text())
    assert state["weekly_reset"] == {"resets_at": 1791162000, "seen_ts": 1790755500}
    assert "last_auto_day" not in state  # manual runs don't use up the automatic run
    assert "SECRETREPLY" not in all_text(grid_home)


def test_claude_is_called_minimally_and_tagged(grid_home, fake_claude):
    fake_claude("meter_stream_ok.jsonl")
    meter.main(["--now"])
    [call] = fake_claude.calls()
    assert call["argv"] == ["-p", "Reply with the single word: ok", "--model", "haiku",
                            "--no-session-persistence", "--output-format", "stream-json", "--verbose",
                            "--tools", "", "--strict-mcp-config",
                            "--system-prompt", "Reply with exactly one word.", "--max-turns", "1"]
    assert call["env"]["CLAUDE_USAGE_GRID_METER"] == "1"
    assert call["env"]["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert "CLAUDECODE" not in call["env"] and "CLAUDE_CODE_ENTRYPOINT" not in call["env"]
    assert call["cwd"] == os.path.realpath(str(grid_home / "meter-cwd"))


def test_scheduled_runs_once_per_slot(grid_home, fake_claude, monkeypatch, new_york):
    fake_claude("meter_stream_ok.jsonl")
    for when in ((2026, 9, 30, 21, 55), (2026, 9, 30, 22, 55)):  # 20:55 slot runs late, once
        monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(*when)))
        meter.main(["--scheduled"])
    assert len(fake_claude.calls()) == 1
    for minute_later in (0, 60):  # 23:55, then launchd again at 00:55 the next day
        monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 23, 55) + minute_later * 60))
        meter.main(["--scheduled"])
    assert len(fake_claude.calls()) == 2
    assert [r["trigger"] for r in jsonl(grid_home / "readings.jsonl")] == ["scheduled", "scheduled"]
    state = json.loads((grid_home / "state" / "meter.json").read_text())
    assert (state["last_auto_slot"], state["last_auto_day"]) == ("2026-09-30T23:55", "2026-09-30")


def test_interval_comes_from_config(grid_home, fake_claude, monkeypatch, new_york):
    fake_claude("meter_stream_ok.jsonl")
    (grid_home / "config.json").write_text(json.dumps({"meter_interval_hours": 24}))
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 20, 55)))
    meter.main(["--scheduled"])
    assert fake_claude.calls() == []


def test_failed_scheduled_run_is_not_retried(grid_home, fake_claude, monkeypatch, new_york):
    fake_claude("meter_stream_not_logged_in.jsonl", exit_code=1)
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 23, 55)))
    assert meter.main(["--scheduled"]) == 1
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 23, 58)))
    meter.main(["--scheduled"])
    assert len(fake_claude.calls()) == 1
    assert not (grid_home / "readings.jsonl").exists()
    [run] = jsonl(grid_home / "meter-runs.jsonl")
    assert run["ok"] is False and run["error"] == "Not logged in · Please run /login"


def test_scheduled_reset_day_uses_pre_reset_slot(grid_home, fake_claude, monkeypatch, new_york):
    fake_claude("meter_stream_ok.jsonl")
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", "1790755500")
    meter.main(["--now"])  # learns the weekly reset (Sun 21:00)
    for when in ((2026, 10, 4, 19, 55), (2026, 10, 4, 20, 55), (2026, 10, 4, 21, 55), (2026, 10, 4, 23, 55)):
        monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(*when)))
        meter.main(["--scheduled"])
    triggers = [r["trigger"] for r in jsonl(grid_home / "readings.jsonl")]
    assert triggers == ["manual", "scheduled", "pre_reset", "scheduled"]  # 17:55 caught up at 19:55


def test_timeout_is_recorded(grid_home, fake_claude):
    fake_claude("meter_stream_ok.jsonl", sleep=5, timeout=1)
    assert meter.main(["--now"]) == 1
    [run] = jsonl(grid_home / "meter-runs.jsonl")
    assert run["error"] == "timed out after 1s"


def test_missing_claude_binary_is_recorded(grid_home):
    grid_home.mkdir(parents=True)
    (grid_home / "config.json").write_text(json.dumps({"claude_bin": "/nonexistent/claude"}))
    assert meter.main(["--now"]) == 1
    [run] = jsonl(grid_home / "meter-runs.jsonl")
    assert run["error"].startswith("could not start /nonexistent/claude")


def test_runs_under_system_python(grid_home, fake_claude):
    fake_claude("meter_stream_ok.jsonl")
    result = run_collector("meter.py", args=("--now",))
    assert result.returncode == 0, result.stderr.decode()
    assert len(jsonl(grid_home / "readings.jsonl")) == 1
