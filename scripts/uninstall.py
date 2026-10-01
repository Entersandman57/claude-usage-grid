#!/usr/bin/env python3
"""Uninstall Claude Usage Grid.

  uninstall.py plan                   show every change; writes nothing
  uninstall.py apply                  remove the integration, keep your data
  uninstall.py apply --delete-data    also delete ~/.claude-usage-grid (logs, chats, backups)
  uninstall.py apply --exact          restore settings.json byte-for-byte from the original backup

apply, in order:
  1. ~/.claude/settings.json: removes the status line and hooks the installer added. If your
     status line was wrapped, the original is put back. Anything else you changed since
     installing stays. (--exact instead restores the file exactly as it was before installing,
     dropping later changes.) The current file is backed up first.
  2. the meter LaunchAgent: unloaded and deleted
  3. launch at login: turned off; the app is quit and deleted from /Applications (with the widget)
  4. the widget's App Group folder (~/Library/Group Containers/<team>.claudeusagegrid)
  5. with --delete-data only: ~/.claude-usage-grid

Not touched: the Claude Code CLI (~/.local/bin/claude) and the PATH line added to ~/.zshrc
during setup, since you may want to keep them; the summary says how to remove them.
"""
import copy
import glob
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import install  # noqa: E402
from install import Paths, read_settings, settings_text, is_ours, LABEL  # noqa: E402

APP = "/Applications/ClaudeUsageGrid.app"


def original_settings(paths):
    """(existed, text) of settings.json before the first install, or None if unknown."""
    saved = install.common.read_json(os.path.join(paths.backups, "original-settings.json"))
    return (saved["existed"], saved["text"]) if isinstance(saved, dict) and "existed" in saved else None


def remove_ours(current, paths, original):
    """current settings minus what the installer added. Empty containers the installer
    created are dropped; ones that existed originally are kept."""
    new = copy.deepcopy(current)
    original_keys = set(original.keys()) if isinstance(original, dict) else set()

    status_line = new.get("statusLine")
    if isinstance(status_line, dict) and is_ours(status_line.get("command"), paths):
        config = install.common.read_json(paths.config, {}) or {}
        wrapped = (config.get("wrapped_statusline") or {}).get("command")
        if wrapped:
            new["statusLine"] = dict(status_line, command=wrapped)
        else:
            del new["statusLine"]

    hooks = new.get("hooks")
    if isinstance(hooks, dict):
        original_hooks = original.get("hooks") if isinstance(original, dict) else None
        original_events = set(original_hooks) if isinstance(original_hooks, dict) else set()
        for event in list(hooks):
            groups = hooks[event] if isinstance(hooks[event], list) else []
            kept_groups = []
            for group in groups:
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    kept_groups.append(group)
                    continue
                handlers = [h for h in group["hooks"] if not (isinstance(h, dict) and is_ours(h.get("command"), paths))]
                if handlers:
                    kept_groups.append(dict(group, hooks=handlers))
                elif len(handlers) == len(group["hooks"]):  # an empty group that was there before
                    kept_groups.append(group)
            if kept_groups or event in original_events:
                hooks[event] = kept_groups
            else:
                del hooks[event]
        if not hooks and "hooks" not in original_keys:
            del new["hooks"]
    return new


def plan_settings(paths, exact=False):
    """(new settings or None to delete the file, current text, note)."""
    current, current_text = read_settings(paths)
    saved = original_settings(paths)
    original = json.loads(saved[1]) if saved and saved[0] and saved[1] and saved[1].strip() else {}
    if exact:
        if not saved:
            raise SystemExit("No original-settings backup found; can't do --exact.")
        return (json.loads(saved[1]) if saved[0] else None), current_text, "restored exactly from the original backup"
    new = remove_ours(current, paths, original)
    delete_file = bool(saved) and not saved[0] and new == {}
    if saved is None:
        note = "no original backup found to compare with"
    elif (saved[0] and new == original) or (not saved[0] and new == {}):
        note = "matches your original settings.json"
    else:
        note = "differs from your original only by changes made after installing"
    return (None if delete_file else new), current_text, note


def group_containers(paths):
    return glob.glob(os.path.join(paths.home, "Library", "Group Containers", "*.claudeusagegrid"))


def plan(paths, exact=False, delete_data=False):
    new, current_text, note = plan_settings(paths, exact)
    print("== %s ==" % paths.settings)
    if new is None:
        print("(file deleted: it didn't exist before installing)")
    else:
        diff = install.settings_diff(current_text, new) if current_text is not None else "(would be created)"
        print(diff or "(no changes)")
    print("Result %s." % note)
    print("\n== also removed ==")
    print("LaunchAgent: %s (%s)" % (paths.plist, "present" if os.path.exists(paths.plist) else "absent"))
    print("Launch at login, and the app: %s (%s)" % (APP, "present" if os.path.exists(APP) else "absent"))
    for container in group_containers(paths) or ["(no App Group folder found)"]:
        print("Widget data: %s" % container)
    print("\n== your data ==")
    print("%s: %s" % (paths.grid, "DELETED" if delete_data else "kept (add --delete-data to delete it)"))
    print("\n== not touched ==")
    print("Claude Code CLI (~/.local/bin/claude). To remove it: rm -rf ~/.local/bin/claude ~/.local/share/claude")
    print("PATH line in ~/.zshrc (\"# Claude Code (added by claude-usage-grid setup)\"). Delete those two lines by hand.")


def apply(paths, exact=False, delete_data=False, system=True):
    new, current_text, note = plan_settings(paths, exact)
    if current_text is not None:
        os.makedirs(paths.backups, exist_ok=True)
        with open(os.path.join(paths.backups, "settings.before-uninstall.%s.json" % time.strftime("%Y%m%d-%H%M%S")),
                  "w", encoding="utf-8") as f:
            f.write(current_text)
    if new is None:
        if os.path.exists(paths.settings):
            os.remove(paths.settings)
    else:
        install.write_settings(paths, new)
    print("settings.json: %s" % note)

    if system:
        domain = "gui/%d" % os.getuid()
        subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, LABEL)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(paths.plist):
        os.remove(paths.plist)
    print("LaunchAgent removed")

    if system and os.path.exists(APP):
        binary = os.path.join(APP, "Contents", "MacOS", "ClaudeUsageGrid")
        subprocess.run([binary, "--login-item", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-x", "ClaudeUsageGrid"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "UsageGridWidget.appex/Contents/MacOS/UsageGridWidget"], stderr=subprocess.DEVNULL)
        shutil.rmtree(APP)
        print("Launch at login turned off; %s deleted (the widget goes with it)" % APP)

    for container in group_containers(paths):
        shutil.rmtree(container, ignore_errors=True)
        print("Removed %s" % container)

    if delete_data:
        shutil.rmtree(paths.grid, ignore_errors=True)
        print("Deleted %s" % paths.grid)
    else:
        print("Kept your data in %s (backups of settings.json are there too)" % paths.grid)


def main(argv):
    args = argv[1:]
    if not args or args[0] not in ("plan", "apply") or set(args[1:]) - {"--exact", "--delete-data"}:
        raise SystemExit(__doc__)
    options = {"exact": "--exact" in args, "delete_data": "--delete-data" in args}
    (plan if args[0] == "plan" else apply)(Paths(), **options)


if __name__ == "__main__":
    main(sys.argv)
