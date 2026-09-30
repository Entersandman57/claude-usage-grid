#!/usr/bin/env python3
"""Install the collectors.

  install.py plan    show every change (settings.json diff, LaunchAgent, files); writes nothing
  install.py apply   back up settings.json, then install everything

apply, in order (scripts exist before settings.json points at them):
  1. copy collectors/*.py to ~/.claude-usage-grid/bin/
  2. create ~/.claude-usage-grid/venv with claude-agent-sdk (for backfill.py)
  3. write config.json (claude_bin, and wrapped_statusline if you had a status line)
  4. back up ~/.claude/settings.json (the pristine original is kept once, for
     uninstall), then merge in statusLine and the SessionStart/UserPromptSubmit hooks
  5. install and load the meter LaunchAgent
  6. run the session backfill once
"""
import copy
import difflib
import glob
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "collectors"))
import common  # noqa: E402

PYTHON = "/usr/bin/python3"
SDK_REQUIREMENT = "claude-agent-sdk==0.2.162"
LABEL = "local.claude-usage-grid.meter"
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit")
HOOK_TIMEOUT_SECONDS = 5
COLLECTOR_FILES = ("common.py", "statusline.py", "hook.py", "meter.py", "backfill.py")


class Paths:
    def __init__(self, home=None, grid=None, claude_dir=None):
        self.home = home or os.path.expanduser("~")
        self.grid = grid or common.data_dir()
        self.claude_dir = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(self.home, ".claude")
        self.settings = os.path.join(self.claude_dir, "settings.json")
        self.bin = os.path.join(self.grid, "bin")
        self.venv = os.path.join(self.grid, "venv")
        self.config = os.path.join(self.grid, "config.json")
        self.backups = os.path.join(self.grid, "backups")
        self.plist = os.path.join(self.home, "Library", "LaunchAgents", LABEL + ".plist")


def read_settings(paths):
    """(parsed settings, raw text or None if the file does not exist)."""
    if not os.path.exists(paths.settings):
        return {}, None
    with open(paths.settings, encoding="utf-8") as f:
        text = f.read()
    return (json.loads(text) if text.strip() else {}), text


def is_ours(command, paths):
    return isinstance(command, str) and os.path.join(paths.bin, "") in command


def merge_settings(current, paths):
    """Add our statusLine and hooks to a copy of current. Returns (new, wrapped_command)."""
    new = copy.deepcopy(current)
    ours = "%s %s" % (PYTHON, os.path.join(paths.bin, "statusline.py"))
    wrapped = None
    existing = new.get("statusLine")
    if isinstance(existing, dict) and existing.get("command") and not is_ours(existing["command"], paths):
        wrapped = existing["command"]
        new["statusLine"] = dict(existing, command=ours)  # keeps padding, refreshInterval, ...
    elif not (isinstance(existing, dict) and is_ours(existing.get("command"), paths)):
        new["statusLine"] = {"type": "command", "command": ours}

    hooks = new.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        installed = any(is_ours(handler.get("command"), paths)
                        for group in groups if isinstance(group, dict)
                        for handler in group.get("hooks", []) if isinstance(handler, dict))
        if not installed:
            groups.append({"hooks": [{
                "type": "command",
                "command": "%s %s %s" % (PYTHON, os.path.join(paths.bin, "hook.py"), event),
                "timeout": HOOK_TIMEOUT_SECONDS,
            }]})
    return new, wrapped


def settings_text(settings):
    return json.dumps(settings, indent=2, ensure_ascii=False) + "\n"


def settings_diff(current_text, new):
    before = (current_text or "").splitlines()
    after = settings_text(new).splitlines()
    label = "settings.json" if current_text is not None else "settings.json (does not exist)"
    return "\n".join(difflib.unified_diff(before, after, label + " (current)",
                                          "settings.json (proposed)", lineterm=""))


def plist_bytes(paths):
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [PYTHON, os.path.join(paths.bin, "meter.py"), "--scheduled"],
        "StartCalendarInterval": {"Minute": 55},
        "ProcessType": "Background",
        "RunAtLoad": False,
        "StandardOutPath": os.path.join(paths.grid, "logs", "meter.out.log"),
        "StandardErrorPath": os.path.join(paths.grid, "logs", "meter.err.log"),
    })


def desired_config(paths, wrapped):
    config = common.read_json(paths.config, {}) or {}
    config.setdefault("claude_bin", os.path.join(paths.home, ".local", "bin", "claude"))
    if wrapped:
        config["wrapped_statusline"] = {"command": wrapped}
    return config


def backup_settings(paths, current_text):
    """Keep the pristine original once (for uninstall) plus a timestamped copy of each apply."""
    os.makedirs(paths.backups, exist_ok=True)
    original = os.path.join(paths.backups, "original-settings.json")
    if not os.path.exists(original):
        common.write_json_atomic(original, {"existed": current_text is not None, "text": current_text,
                                            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    if current_text is not None:
        stamped = os.path.join(paths.backups, "settings.%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        with open(stamped, "w", encoding="utf-8") as f:
            f.write(current_text)


def write_settings(paths, new):
    os.makedirs(paths.claude_dir, exist_ok=True)
    tmp = paths.settings + ".claude-usage-grid.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(settings_text(new))
    os.replace(tmp, paths.settings)


def find_sdk_python():
    """A Python 3.10+ for the SDK venv (the collectors themselves use /usr/bin/python3)."""
    candidates = [sys.executable, shutil.which("python3"), "/opt/homebrew/bin/python3"]
    candidates += glob.glob("/Library/Frameworks/Python.framework/Versions/3.*/bin/python3")
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            check = subprocess.run([candidate, "-c", "import sys; print(sys.version_info >= (3, 10))"],
                                   stdout=subprocess.PIPE, text=True)
            if check.stdout.strip() == "True":
                return candidate
    raise SystemExit("No Python 3.10+ found for the claude-agent-sdk venv.")


def venv_ready(paths):
    python = os.path.join(paths.venv, "bin", "python")
    return os.path.exists(python) and subprocess.run(
        [python, "-c", "import claude_agent_sdk"], stderr=subprocess.DEVNULL).returncode == 0


def ensure_venv(paths):
    if venv_ready(paths):
        return
    subprocess.run([find_sdk_python(), "-m", "venv", paths.venv], check=True)
    subprocess.run([os.path.join(paths.venv, "bin", "pip"), "install", "-q", SDK_REQUIREMENT], check=True)


def install_collectors(paths):
    os.makedirs(paths.bin, exist_ok=True)
    for name in COLLECTOR_FILES:
        target = os.path.join(paths.bin, name)
        shutil.copyfile(os.path.join(REPO, "collectors", name), target)
        os.chmod(target, 0o755)


def load_launch_agent(paths):
    os.makedirs(os.path.dirname(paths.plist), exist_ok=True)
    os.makedirs(os.path.join(paths.grid, "logs"), exist_ok=True)
    with open(paths.plist, "wb") as f:
        f.write(plist_bytes(paths))
    domain = "gui/%d" % os.getuid()
    subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, LABEL)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "bootstrap", domain, paths.plist], check=True)


def plan(paths):
    current, current_text = read_settings(paths)
    new, wrapped = merge_settings(current, paths)
    print("== %s ==" % paths.settings)
    print(settings_diff(current_text, new) if new != current or current_text is None else "(no changes)")
    if wrapped:
        print("\nYour existing status line will be wrapped; its output stays the same:\n  %s" % wrapped)

    existing_plist = open(paths.plist, "rb").read() if os.path.exists(paths.plist) else None
    state = "unchanged" if existing_plist == plist_bytes(paths) else ("new" if existing_plist is None else "changed")
    print("\n== LaunchAgent %s (%s) ==" % (paths.plist, state))
    print(plist_bytes(paths).decode("utf-8").strip())

    print("\n== Files ==")
    print("%s/: %s" % (paths.bin, ", ".join(COLLECTOR_FILES)))
    print("%s: %s (%s)" % (paths.venv, SDK_REQUIREMENT, "exists" if venv_ready(paths) else "create"))
    print("%s: %s" % (paths.config, json.dumps(desired_config(paths, wrapped))))
    print("backups: %s/" % paths.backups)


def apply(paths):
    current, current_text = read_settings(paths)
    new, wrapped = merge_settings(current, paths)
    install_collectors(paths)
    ensure_venv(paths)
    common.write_json_atomic(paths.config, desired_config(paths, wrapped))
    backup_settings(paths, current_text)
    if new != current or current_text is None:
        write_settings(paths, new)
    load_launch_agent(paths)
    subprocess.run([os.path.join(paths.venv, "bin", "python"), os.path.join(paths.bin, "backfill.py")], check=True)
    print("Installed. Settings backup: %s" % paths.backups)


def main(argv):
    if len(argv) != 2 or argv[1] not in ("plan", "apply"):
        raise SystemExit(__doc__)
    (plan if argv[1] == "plan" else apply)(Paths())


if __name__ == "__main__":
    main(sys.argv)
