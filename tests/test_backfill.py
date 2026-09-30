import json
import os

import claude_agent_sdk
import pytest
from claude_agent_sdk import SDKSessionInfo

import backfill
from conftest import all_text


def info(session_id, title=None, cwd="/Users/me/proj", created_ms=1790000000000, modified_ms=1790100000000):
    return SDKSessionInfo(
        session_id=session_id, summary="SECRET first prompt as summary", last_modified=modified_ms,
        file_size=1234, custom_title=title, first_prompt="SECRET first prompt", git_branch="main",
        cwd=cwd, tag=None, created_at=created_ms)


def sessions(grid_home):
    return json.loads((grid_home / "sessions.json").read_text())["sessions"]


def test_keeps_ids_titles_folders_and_times_only(grid_home, monkeypatch):
    monkeypatch.setattr(claude_agent_sdk, "list_sessions", lambda: [info("a", "Fix login bug"), info("b")])
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", "1790200000")
    backfill.main()
    assert sessions(grid_home) == {
        "a": {"session_id": "a", "title": "Fix login bug", "cwd": "/Users/me/proj", "created_at": 1790000000.0,
              "last_modified": 1790100000.0, "transcript_present": True, "first_seen": 1790200000},
        "b": {"session_id": "b", "title": None, "cwd": "/Users/me/proj", "created_at": 1790000000.0,
              "last_modified": 1790100000.0, "transcript_present": True, "first_seen": 1790200000},
    }
    assert "SECRET" not in all_text(grid_home)


def test_deleted_transcripts_stay_listed_without_resume(grid_home, monkeypatch):
    monkeypatch.setattr(claude_agent_sdk, "list_sessions", lambda: [info("a", "Old"), info("b", "New")])
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", "100")
    backfill.main()
    monkeypatch.setattr(claude_agent_sdk, "list_sessions", lambda: [info("b", None, modified_ms=1790300000000)])
    monkeypatch.setenv("CLAUDE_USAGE_GRID_NOW", "200")
    backfill.main()
    result = sessions(grid_home)
    assert result["a"]["transcript_present"] is False and result["a"]["title"] == "Old"
    assert result["b"]["transcript_present"] is True
    assert result["b"]["title"] == "New"  # a title once seen is kept
    assert result["b"]["last_modified"] == 1790300000.0 and result["b"]["first_seen"] == 100


@pytest.mark.skipif(not os.path.isdir(os.path.expanduser("~/.claude/projects")), reason="no local sessions")
def test_real_list_sessions_reads_this_machine(grid_home):
    backfill.main()
    result = sessions(grid_home)
    assert result, "expected at least this session"
    for rec in result.values():
        assert set(rec) == {"session_id", "title", "cwd", "created_at", "last_modified",
                            "transcript_present", "first_seen"}
