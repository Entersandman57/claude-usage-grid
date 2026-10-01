PY := .venv/bin/python

.PHONY: test plan install app app-test uninstall-plan uninstall

test:
	$(PY) -m pytest -q

# Show every change the installer would make; writes nothing.
plan:
	/usr/bin/python3 scripts/install.py plan

# Back up ~/.claude/settings.json, then install collectors, venv, settings and LaunchAgent.
install:
	/usr/bin/python3 scripts/install.py apply

# Build the app + widget (signed with your Personal Team), install to /Applications, relaunch.
app:
	scripts/build_app.sh

# Swift unit tests (layout, decoding, links).
app-test:
	scripts/build_app.sh test

# Show everything the uninstaller would change; writes nothing.
uninstall-plan:
	/usr/bin/python3 scripts/uninstall.py plan

# Remove the integration (settings entries, LaunchAgent, login item, app, widget); keeps your data.
uninstall:
	/usr/bin/python3 scripts/uninstall.py apply
