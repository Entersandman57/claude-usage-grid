PY := .venv/bin/python

.PHONY: test plan install

test:
	$(PY) -m pytest -q

# Show every change the installer would make; writes nothing.
plan:
	/usr/bin/python3 scripts/install.py plan

# Back up ~/.claude/settings.json, then install collectors, venv, settings and LaunchAgent.
install:
	/usr/bin/python3 scripts/install.py apply
