import json
import os
import statistics
import subprocess
import time

from conftest import COLLECTORS, SYSTEM_PYTHON, read_fixture, run_collector

FULL = read_fixture("statusline_input.json", "rb")
T0 = 1790755338.0


def readings(grid_home):
    path = grid_home / "readings.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def run(stdin, at=T0, env=None):
    env = dict(env or {}, CLAUDE_USAGE_GRID_NOW=str(at))
    return run_collector("statusline.py", stdin, env=env)


def with_limits(**windows):
    data = json.loads(FULL)
    data["rate_limits"] = windows
    return json.dumps(data).encode()


def test_prints_both_windows_and_logs_first_reading(grid_home):
    result = run(FULL)
    assert result.returncode == 0
    assert result.stdout.decode() == "5h 24% · wk 41%\n"  # 23.5 rounds up, 41.2 down
    [reading] = readings(grid_home)
    assert reading == {
        "ts": T0, "source": "statusline",
        "session_id": "07f8a11d-158d-4501-be5e-513ccd2f5af3", "session_name": "usage grid probe",
        "project_dir": "/Users/me/proj",
        "five_hour": {"used_percentage": 23.5, "resets_at": 1790771400},
        "seven_day": {"used_percentage": 41.2, "resets_at": 1791162000},
        "changed": True,
    }


def test_unchanged_values_log_at_most_once_a_minute(grid_home):
    run(FULL, at=T0)
    run(FULL, at=T0 + 10)
    run(FULL, at=T0 + 59)
    assert len(readings(grid_home)) == 1
    run(FULL, at=T0 + 61)
    logged = readings(grid_home)
    assert len(logged) == 2 and logged[1]["changed"] is False


def test_changed_values_log_immediately(grid_home):
    run(FULL, at=T0)
    bumped = with_limits(five_hour={"used_percentage": 24, "resets_at": 1790771400},
                         seven_day={"used_percentage": 41.2, "resets_at": 1791162000})
    run(bumped, at=T0 + 5)
    logged = readings(grid_home)
    assert [r["changed"] for r in logged] == [True, True]
    assert logged[1]["five_hour"]["used_percentage"] == 24


def test_new_resets_at_counts_as_a_change(grid_home):
    run(FULL, at=T0)
    moved = with_limits(five_hour={"used_percentage": 23.5, "resets_at": 1790789400},
                        seven_day={"used_percentage": 41.2, "resets_at": 1791162000})
    run(moved, at=T0 + 5)
    assert len(readings(grid_home)) == 2


def test_missing_window_is_shown_and_logged_as_absent(grid_home):
    result = run(with_limits(five_hour={"used_percentage": 12, "resets_at": 1790771400}))
    assert result.stdout.decode() == "5h 12% · wk --\n"
    [reading] = readings(grid_home)
    assert reading["seven_day"] is None


def test_no_rate_limits_prints_placeholders_and_logs_nothing(grid_home):
    data = json.loads(FULL)
    del data["rate_limits"]
    result = run(json.dumps(data).encode())
    assert result.returncode == 0
    assert result.stdout.decode() == "5h -- · wk --\n"
    assert readings(grid_home) == []


def test_garbage_input_still_prints(grid_home):
    for stdin in (b"", b"not json", b"[1, 2]", b'{"rate_limits": {"five_hour": {"used_percentage": "12"}}}'):
        result = run(stdin)
        assert result.returncode == 0
        assert result.stdout.decode() == "5h -- · wk --\n"
    assert readings(grid_home) == []


def test_unwritable_data_dir_never_breaks_the_status_line(tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    result = run(FULL, env={"CLAUDE_USAGE_GRID_HOME": str(blocker / "grid")})
    assert result.returncode == 0
    assert result.stdout.decode() == "5h 24% · wk 41%\n"
    assert result.stderr == b""


def test_wrapped_status_line_output_is_byte_for_byte_identical(grid_home, tmp_path):
    original = tmp_path / "my_statusline.py"
    original.write_text(
        "import json, sys\n"
        "d = json.load(sys.stdin)\n"
        "sys.stdout.write('\\033[32m[%s]\\033[0m %s\\n' % (d['model']['display_name'], d['workspace']['current_dir']))\n"
        "sys.stdout.write('second line\\n')\n")
    command = "%s %s" % (SYSTEM_PYTHON, original)
    grid_home.mkdir(parents=True)
    (grid_home / "config.json").write_text(json.dumps({"wrapped_statusline": {"command": command}}))

    expected = subprocess.run(command, shell=True, input=FULL, stdout=subprocess.PIPE).stdout
    result = run(FULL)
    assert result.stdout == expected == b"\x1b[32m[Opus]\x1b[0m /Users/me/proj/sub\nsecond line\n"
    assert len(readings(grid_home)) == 1  # still logs underneath the wrapped output


def test_is_fast(grid_home):
    durations = []
    for i in range(7):
        start = time.monotonic()
        run(FULL, at=T0 + i * 120)
        durations.append(time.monotonic() - start)
    median = statistics.median(durations)
    print("\nstatusline.py median wall time: %.0f ms" % (median * 1000))
    assert median < 0.3


def test_collectors_compile_under_python39():
    for name in ("common.py", "statusline.py", "hook.py", "meter.py"):
        check = subprocess.run([SYSTEM_PYTHON, "-m", "py_compile", os.path.join(COLLECTORS, name)])
        assert check.returncode == 0, name
