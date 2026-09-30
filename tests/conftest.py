import os
import subprocess
import sys
import time

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTORS = os.path.join(REPO, "collectors")
FIXTURES = os.path.join(REPO, "tests", "fixtures")
SYSTEM_PYTHON = "/usr/bin/python3"  # the collectors' real runtime (3.9)

sys.path.insert(0, COLLECTORS)
sys.path.insert(0, os.path.join(REPO, "scripts"))


def fixture_path(name):
    return os.path.join(FIXTURES, name)


def read_fixture(name, mode="r"):
    with open(fixture_path(name), mode) as f:
        return f.read()


def all_text(directory):
    """Concatenated contents of every file under directory (to prove text was not stored)."""
    chunks = []
    for root, _, files in os.walk(directory):
        for name in files:
            with open(os.path.join(root, name), "rb") as f:
                chunks.append(f.read().decode("utf-8", "replace"))
    return "\n".join(chunks)


def run_collector(name, stdin=b"", args=(), env=None):
    """Run a collector the way Claude Code / launchd does: /usr/bin/python3, fresh process."""
    full_env = dict(os.environ)
    full_env.pop("CLAUDE_USAGE_GRID_METER", None)
    full_env.update(env or {})
    return subprocess.run([SYSTEM_PYTHON, os.path.join(COLLECTORS, name)] + list(args),
                          input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env=full_env, timeout=60)


@pytest.fixture
def grid_home(tmp_path, monkeypatch):
    home = tmp_path / "grid"
    monkeypatch.setenv("CLAUDE_USAGE_GRID_HOME", str(home))
    monkeypatch.delenv("CLAUDE_USAGE_GRID_NOW", raising=False)
    return home


@pytest.fixture
def new_york():
    """Pin the local time zone to the user's (DST ends 2026-11-01)."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def local_epoch(year, month, day, hour, minute, second=0):
    """Epoch seconds for a local wall-clock time (use with the new_york fixture)."""
    return time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
