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

@pytest.mark.parametrize("when, last_day, expected", [
    ((2026, 9, 30, 12, 0), None, None),                 # ordinary afternoon
    ((2026, 9, 30, 23, 54), None, None),
    ((2026, 9, 30, 23, 55), None, "nightly"),
    ((2026, 9, 30, 23, 54, 40), None, "nightly"),       # launchd a few seconds early
    ((2026, 9, 30, 23, 55), "2026-09-30", None),        # already ran today
    ((2026, 10, 1, 7, 10), "2026-09-29", None),         # woke after a missed night: no catch-up
    ((2026, 10, 4, 20, 54), None, None),                # reset day, before the pre-reset slot
    ((2026, 10, 4, 20, 55), None, "pre_reset"),         # reset day: last :55 before 21:00
    ((2026, 10, 4, 20, 59, 30), None, None),            # too close to the reset
    ((2026, 10, 4, 21, 10), None, None),                # pre-reset slot missed ...
    ((2026, 10, 4, 23, 55), None, "nightly"),           # ... so the day's run is at 23:55
    ((2026, 10, 4, 23, 55), "2026-10-04", None),        # pre-reset run already happened
    ((2026, 10, 11, 20, 55), None, "pre_reset"),        # next week, projected from the known reset
    ((2026, 11, 1, 19, 55), None, "pre_reset"),         # DST ended: reset is 20:00 EST
    ((2026, 11, 1, 20, 55), None, None),
    ((2026, 11, 1, 23, 55), None, "nightly"),
])
def test_due_run(new_york, when, last_day, expected):
    assert local_epoch(2026, 10, 4, 21, 0) == REAL_WEEKLY_RESET
    assert meter.due_run(local_epoch(*when), last_day, REAL_WEEKLY_RESET) == expected


def test_pre_reset_slot_is_last_wakeup_before_a_half_hour_reset(new_york):
    reset = local_epoch(2026, 10, 7, 21, 30)
    assert meter.due_run(local_epoch(2026, 10, 7, 20, 55), None, reset) == "pre_reset"
    assert meter.due_run(local_epoch(2026, 10, 7, 21, 55), None, reset) is None


def test_reset_just_after_midnight_uses_normal_nightly_slots(new_york):
    reset = local_epoch(2026, 10, 5, 0, 30)
    assert meter.due_run(local_epoch(2026, 10, 4, 23, 55), None, reset) == "nightly"
    assert meter.due_run(local_epoch(2026, 10, 5, 0, 20), "2026-10-04", reset) is None
    assert meter.due_run(local_epoch(2026, 10, 5, 23, 55), "2026-10-04", reset) == "nightly"


def test_unknown_reset_means_nightly_only(new_york):
    assert meter.due_run(local_epoch(2026, 10, 4, 20, 55), None, None) is None
    assert meter.due_run(local_epoch(2026, 10, 4, 23, 55), None, None) == "nightly"


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


def test_scheduled_run_happens_once_per_day(grid_home, fake_claude, monkeypatch, new_york):
    fake_claude("meter_stream_ok.jsonl")
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 22, 55)))
    meter.main(["--scheduled"])
    assert fake_claude.calls() == []
    for minute_later in (0, 60):  # 23:55, then launchd again at 00:55 the next day
        monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", str(local_epoch(2026, 9, 30, 23, 55) + minute_later * 60))
        meter.main(["--scheduled"])
    assert len(fake_claude.calls()) == 1
    assert jsonl(grid_home / "readings.jsonl")[0]["trigger"] == "nightly"


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
    assert triggers == ["manual", "pre_reset"]


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
