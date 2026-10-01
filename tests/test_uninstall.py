import json
import os

import pytest

import install
import uninstall


@pytest.fixture
def paths(tmp_path):
    return install.Paths(home=str(tmp_path / "home"), grid=str(tmp_path / "home" / ".claude-usage-grid"))


def installed(paths, original_text, config=None):
    """Simulate install.py apply: back up the original, write merged settings."""
    original = json.loads(original_text) if original_text else {}
    new, wrapped = install.merge_settings(original, paths)
    install.backup_settings(paths, original_text)
    install.write_settings(paths, new)
    install.common.write_json_atomic(paths.config, config or install.desired_config(paths, wrapped))
    return new


def settings(paths):
    return json.loads(open(paths.settings).read())


def test_round_trip_restores_theme_only_settings(paths):
    installed(paths, '{\n  "theme": "dark"\n}\n')
    new, _, note = uninstall.plan_settings(paths)
    assert new == {"theme": "dark"} and note == "matches your original settings.json"


def test_round_trip_puts_back_a_wrapped_status_line_and_other_hooks(paths):
    original = {"statusLine": {"type": "command", "command": "~/.claude/statusline.sh", "padding": 2},
                "hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}],
                          "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
    installed(paths, json.dumps(original, indent=2))
    new, _, note = uninstall.plan_settings(paths)
    assert new == original and note == "matches your original settings.json"


def test_empty_hooks_object_that_existed_is_kept(paths):
    installed(paths, '{"hooks": {}}')
    assert uninstall.plan_settings(paths)[0] == {"hooks": {}}


def test_changes_made_after_install_survive(paths):
    after_install = installed(paths, '{"theme": "dark"}')
    after_install["model"] = "opus"
    after_install["hooks"]["PreToolUse"] = [{"hooks": [{"type": "command", "command": "lint"}]}]
    install.write_settings(paths, after_install)
    new, _, note = uninstall.plan_settings(paths)
    assert new == {"theme": "dark", "model": "opus",
                   "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "lint"}]}]}}
    assert note == "differs from your original only by changes made after installing"


def test_settings_file_is_deleted_if_it_did_not_exist_before(paths):
    installed(paths, None)
    assert uninstall.plan_settings(paths)[0] is None


def test_exact_restores_the_original_text(paths):
    after_install = installed(paths, '{"theme": "dark"}')
    after_install["model"] = "opus"
    install.write_settings(paths, after_install)
    new, _, note = uninstall.plan_settings(paths, exact=True)
    assert new == {"theme": "dark"} and "exactly" in note


def test_plan_writes_nothing(paths, capsys):
    installed(paths, '{"theme": "dark"}')
    before = open(paths.settings).read()
    uninstall.plan(paths)
    assert open(paths.settings).read() == before
    out = capsys.readouterr().out
    assert "matches your original settings.json" in out and "kept (add --delete-data" in out


def test_apply_removes_integration_and_keeps_data(paths):
    installed(paths, '{"theme": "dark"}')
    os.makedirs(os.path.dirname(paths.plist))
    open(paths.plist, "wb").write(install.plist_bytes(paths))
    container = os.path.join(paths.home, "Library", "Group Containers", "TEAM123.claudeusagegrid")
    os.makedirs(container)
    open(os.path.join(container, "snapshot.json"), "w").write("{}")
    open(os.path.join(paths.grid, "readings.jsonl"), "w").write("{}\n")

    uninstall.apply(paths, system=False)

    assert settings(paths) == {"theme": "dark"}
    assert not os.path.exists(paths.plist) and not os.path.exists(container)
    assert os.path.exists(os.path.join(paths.grid, "readings.jsonl"))
    assert any(name.startswith("settings.before-uninstall.") for name in os.listdir(paths.backups))


def test_apply_delete_data(paths):
    installed(paths, '{"theme": "dark"}')
    uninstall.apply(paths, delete_data=True, system=False)
    assert not os.path.exists(paths.grid)
    assert settings(paths) == {"theme": "dark"}
