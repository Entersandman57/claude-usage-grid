import json
import plistlib

import pytest

import install


@pytest.fixture
def paths(tmp_path):
    return install.Paths(home=str(tmp_path / "home"), grid=str(tmp_path / "home" / ".claude-usage-grid"))


def ours(paths, name, *args):
    return " ".join(["/usr/bin/python3", "%s/%s" % (paths.bin, name)] + list(args))


def test_merge_into_theme_only_settings(paths):
    new, wrapped = install.merge_settings({"theme": "dark"}, paths)
    assert wrapped is None
    assert new == {
        "theme": "dark",
        "statusLine": {"type": "command", "command": ours(paths, "statusline.py")},
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": ours(paths, "hook.py", "SessionStart"),
                                         "timeout": 5}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command",
                                             "command": ours(paths, "hook.py", "UserPromptSubmit"),
                                             "timeout": 5}]}],
        },
    }


def test_existing_status_line_is_wrapped_with_its_options_kept(paths):
    current = {"statusLine": {"type": "command", "command": "~/.claude/statusline.sh", "padding": 2,
                              "refreshInterval": 5}}
    new, wrapped = install.merge_settings(current, paths)
    assert wrapped == "~/.claude/statusline.sh"
    assert new["statusLine"] == {"type": "command", "command": ours(paths, "statusline.py"), "padding": 2,
                                 "refreshInterval": 5}


def test_existing_hooks_are_kept(paths):
    theirs = {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
    new, _ = install.merge_settings({"hooks": {"SessionStart": [theirs], "Stop": [theirs]}}, paths)
    assert new["hooks"]["SessionStart"][0] == theirs and len(new["hooks"]["SessionStart"]) == 2
    assert new["hooks"]["Stop"] == [theirs]


def test_merge_is_idempotent(paths):
    once, _ = install.merge_settings({"theme": "dark"}, paths)
    twice, wrapped = install.merge_settings(once, paths)
    assert twice == once and wrapped is None


def test_diff_shows_only_additions(paths):
    current_text = '{\n  "theme": "dark"\n}\n'
    new, _ = install.merge_settings({"theme": "dark"}, paths)
    diff = install.settings_diff(current_text, new)
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert removed == ['-  "theme": "dark"']  # only re-emitted with a trailing comma
    assert '+  "theme": "dark",' in diff


def test_backup_keeps_pristine_original_once(paths):
    install.backup_settings(paths, '{"theme": "dark"}')
    install.backup_settings(paths, '{"theme": "dark", "statusLine": {}}')
    original = json.loads(open("%s/original-settings.json" % paths.backups).read())
    assert original["existed"] is True and original["text"] == '{"theme": "dark"}'


def test_backup_records_absent_original(paths):
    install.backup_settings(paths, None)
    original = json.loads(open("%s/original-settings.json" % paths.backups).read())
    assert original == {"existed": False, "text": None, "saved_at": original["saved_at"]}


def test_write_settings_round_trips(paths):
    new, _ = install.merge_settings({"theme": "dark"}, paths)
    install.write_settings(paths, new)
    assert install.read_settings(paths)[0] == new


def test_plist_schedules_hourly_meter(paths):
    plist = plistlib.loads(install.plist_bytes(paths))
    assert plist["ProgramArguments"] == ["/usr/bin/python3", "%s/meter.py" % paths.bin, "--scheduled"]
    assert plist["StartCalendarInterval"] == {"Minute": 55}
    assert plist["RunAtLoad"] is False


def test_installed_aggregator_runs_from_bin(paths):
    import os
    import subprocess
    install.install_collectors(paths)
    assert sorted(os.listdir(paths.bin)) == sorted(name for _, name in install.INSTALLED_FILES)
    env = dict(os.environ, CLAUDE_USAGE_GRID_HOME=paths.grid)
    result = subprocess.run(["/usr/bin/python3", os.path.join(paths.bin, "aggregate.py")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode()
    assert os.path.exists(os.path.join(paths.grid, "out", "snapshot.json"))


def test_plan_writes_nothing(paths, capsys):
    install.plan(paths)
    out = capsys.readouterr().out
    assert "settings.json (does not exist)" in out
    import os
    assert not os.path.exists(paths.home)
