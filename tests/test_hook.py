import json

from conftest import all_text, run_collector

SECRET = "SECRET PROMPT TEXT do not store"
PROMPT_INPUT = {
    "session_id": "762edcb4-6ae2-4cce-a44a-7660148e7ab7",
    "prompt_id": "550e8400-e29b-41d4-a716-446655440000",
    "transcript_path": "/Users/me/.claude/projects/x/762edcb4.jsonl",
    "cwd": "/Users/me/code/proj",
    "permission_mode": "default",
    "hook_event_name": "UserPromptSubmit",
    "prompt_text": SECRET,
    "prompt": SECRET,
}
DESKTOP = {"CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "CLAUDE_USAGE_GRID_NOW": "1790755400.25"}


def activity(grid_home):
    path = grid_home / "activity.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def run_hook(payload, args=("UserPromptSubmit",), env=DESKTOP):
    stdin = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return run_collector("hook.py", stdin, args=args, env=env)


def test_prompt_submit_records_only_whitelisted_fields(grid_home):
    result = run_hook(PROMPT_INPUT)
    assert result.returncode == 0
    assert result.stdout == b""  # stdout would be injected into Claude's context
    assert activity(grid_home) == [{
        "ts": 1790755400.25, "event": "UserPromptSubmit",
        "session_id": "762edcb4-6ae2-4cce-a44a-7660148e7ab7",
        "cwd": "/Users/me/code/proj", "entrypoint": "claude-desktop",
    }]
    assert "SECRET" not in all_text(grid_home)


def test_session_start_records_source_and_title(grid_home):
    payload = {"session_id": "abc", "cwd": "/w", "hook_event_name": "SessionStart", "source": "resume",
               "session_title": "auth-refactor", "model": "claude-opus-5", "context_tokens": 182340}
    run_hook(payload, args=("SessionStart",))
    [record] = activity(grid_home)
    assert record["event"] == "SessionStart"
    assert record["source"] == "resume" and record["title"] == "auth-refactor"
    assert "context_tokens" not in record and "model" not in record


def test_event_name_falls_back_to_argument(grid_home):
    run_hook({"session_id": "abc", "cwd": "/w"}, args=("SessionStart",))
    assert activity(grid_home)[0]["event"] == "SessionStart"


def test_meter_calls_are_ignored(grid_home):
    result = run_hook(PROMPT_INPUT, env=dict(DESKTOP, CLAUDE_USAGE_GRID_METER="1"))
    assert result.returncode == 0 and result.stdout == b""
    assert activity(grid_home) == []


def test_bad_input_is_silent(grid_home):
    for stdin in (b"", b"not json", b"[]", json.dumps({"cwd": "/w"}).encode()):
        result = run_hook(stdin)
        assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
    assert activity(grid_home) == []


def test_unwritable_data_dir_is_silent(tmp_path):
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    result = run_hook(PROMPT_INPUT, env=dict(DESKTOP, CLAUDE_USAGE_GRID_HOME=str(blocker / "grid")))
    assert result.returncode == 0 and result.stdout == b"" and result.stderr == b""
