import json
import zipfile

import pytest

import import_chats
from conftest import all_text, run_collector

SECRET = "SECRET message text that must never be stored"


def message(created_at, sender="human"):
    return {"uuid": "m-" + str(created_at), "text": SECRET, "sender": sender, "created_at": created_at,
            "updated_at": created_at, "content": [{"type": "text", "text": SECRET}],
            "attachments": [], "files": []}


def conversation(uuid, name, *times, **extra):
    record = {"uuid": uuid, "name": name, "summary": SECRET, "created_at": times[0] if times else None,
              "updated_at": times[-1] if times else None, "account": {"uuid": "acct"},
              "chat_messages": [message(t) for t in times]}
    record.update(extra)
    return record


def make_export(tmp_path, conversations, inner="conversations.json", name="data-2026-09-30-batch-0000.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(inner, json.dumps(conversations))
        archive.writestr("users.json", json.dumps([{"uuid": "acct", "email_address": "x@example.com"}]))
        archive.writestr("projects.json", "[]")
    return path


def chats(grid_home):
    return json.loads((grid_home / "chats.json").read_text())


def test_keeps_only_uuid_title_and_local_days(grid_home, tmp_path, new_york):
    export = make_export(tmp_path, [
        conversation("c1", "Essay outline", "2026-09-28T14:00:00.123456Z", "2026-09-30T03:30:00Z"),
        conversation("c2", "Recipes", "2026-09-29T12:00:00+00:00"),
    ])
    summary = import_chats.import_export(str(export), ts=100)
    stored = chats(grid_home)
    assert stored["chats"] == {
        # 03:30 UTC on Sep 30 is 23:30 on Sep 29 in New York
        "c1": {"uuid": "c1", "title": "Essay outline", "days": ["2026-09-28", "2026-09-29"]},
        "c2": {"uuid": "c2", "title": "Recipes", "days": ["2026-09-29"]},
    }
    assert summary["imported"] == 2 and summary["conversations_in_export"] == 2
    assert "SECRET" not in all_text(grid_home)
    assert "x@example.com" not in all_text(grid_home)


def test_imported_through_is_the_later_of_last_message_and_export_date(grid_home, tmp_path, new_york):
    export = make_export(tmp_path, [conversation("c1", "Old", "2026-09-20T15:00:00Z")])
    summary = import_chats.import_export(str(export), ts=100)
    # the ZIP was written just now, so the export date is today, after the last message
    assert summary["last_day"] == "2026-09-20"
    assert summary["imported_through"] >= "2026-09-20"
    assert chats(grid_home)["imported_through"] == summary["imported_through"]


@pytest.mark.parametrize("value, expected", [
    ("2026-09-30T12:34:56.789012Z", "2026-09-30T12:34:56.789012+00:00"),
    ("2026-09-30T12:34:56Z", "2026-09-30T12:34:56+00:00"),
    ("2026-09-30T12:34:56.7+02:00", "2026-09-30T12:34:56.700000+02:00"),
    ("2026-09-30T12:34:56.123456789Z", "2026-09-30T12:34:56.123456+00:00"),
    ("2026-09-30 12:34:56", "2026-09-30T12:34:56+00:00"),
    ("2026-09-30", "2026-09-30T00:00:00+00:00"),
    (1790772896, "2026-09-30T12:54:56+00:00"),
    (1790772896000, "2026-09-30T12:54:56+00:00"),
])
def test_parses_timestamp_variants(value, expected):
    assert import_chats.parse_time(value).isoformat() == expected


@pytest.mark.parametrize("value", [None, "", "yesterday", "2026-13-45T00:00:00Z", {}, [], True])
def test_rejects_unusable_timestamps(value):
    assert import_chats.parse_time(value) is None


def test_defensive_about_odd_conversations(grid_home, tmp_path, new_york):
    export = make_export(tmp_path, [
        conversation("c1", "  ", "2026-09-29T12:00:00Z"),                       # blank title
        {"id": "c2", "title": "Alt keys", "messages": [{"create_time": 1790600000}]},
        {"uuid": "c3", "name": "No message times", "chat_messages": [{"text": SECRET}],
         "created_at": "2026-09-01T12:00:00Z", "updated_at": "2026-09-02T12:00:00Z"},
        {"name": "No id", "chat_messages": [message("2026-09-29T12:00:00Z")]},
        {"uuid": "c5", "name": "No dates at all"},
        "not an object",
        conversation("c6", None, "2026-09-29T12:00:00Z", extra_unknown_field={"x": 1}),
    ])
    summary = import_chats.import_export(str(export), ts=100)
    stored = chats(grid_home)["chats"]
    assert stored["c1"]["title"] is None
    assert stored["c2"] == {"uuid": "c2", "title": "Alt keys", "days": ["2026-09-28"]}
    assert stored["c3"]["days"] == ["2026-09-01", "2026-09-02"]
    assert summary["dated_by_conversation_times"] == 1
    assert summary["skipped"] == {"no id": 1, "no dates": 1, "not an object": 1}
    assert sorted(stored) == ["c1", "c2", "c3", "c6"]


def test_finds_conversations_json_in_a_subfolder(grid_home, tmp_path, new_york):
    export = make_export(tmp_path, [conversation("c1", "Nested", "2026-09-29T12:00:00Z")],
                         inner="export/conversations.json")
    assert import_chats.import_export(str(export), ts=1)["imported"] == 1


def test_accepts_an_unzipped_folder_or_the_json_file(grid_home, tmp_path, new_york):
    folder = tmp_path / "unzipped"
    folder.mkdir()
    (folder / "conversations.json").write_text(json.dumps({"conversations": [
        conversation("c1", "Wrapped list", "2026-09-29T12:00:00Z")]}))
    assert import_chats.import_export(str(folder), ts=1)["imported"] == 1
    assert import_chats.import_export(str(folder / "conversations.json"), ts=2)["imported"] == 1


def test_reimport_updates_and_keeps_chats_deleted_since(grid_home, tmp_path, new_york):
    first = make_export(tmp_path, [conversation("c1", "Kept", "2026-09-20T12:00:00Z"),
                                   conversation("c2", "Renamed later", "2026-09-21T12:00:00Z")], name="a.zip")
    import_chats.import_export(str(first), ts=1)
    second = make_export(tmp_path, [conversation("c2", "New title", "2026-09-21T12:00:00Z",
                                                 "2026-09-30T12:00:00Z")], name="b.zip")
    summary = import_chats.import_export(str(second), ts=2)
    stored = chats(grid_home)["chats"]
    assert stored["c1"]["title"] == "Kept"
    assert stored["c2"] == {"uuid": "c2", "title": "New title", "days": ["2026-09-21", "2026-09-30"]}
    assert summary["total_chats_known"] == 2


@pytest.mark.parametrize("contents, error", [
    (b"not a zip and not json", "Expecting value"),
    (None, "no conversations.json"),
])
def test_bad_files_report_an_error(grid_home, tmp_path, contents, error):
    path = tmp_path / "bad.zip"
    if contents is None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("readme.txt", "hi")
    else:
        path.write_bytes(contents)
    result = run_collector("import_chats.py", args=(str(path),))
    assert result.returncode == 1
    summary = json.loads(result.stdout)
    assert summary["ok"] is False and error in summary["error"]
    assert not (grid_home / "chats.json").exists()


def test_not_a_list_is_an_error(grid_home, tmp_path):
    path = make_export(tmp_path, {"unexpected": True})
    result = run_collector("import_chats.py", args=(str(path),))
    assert json.loads(result.stdout) == {"ok": False, "error": "conversations.json isn't a list of conversations"}


def test_cli_under_system_python(grid_home, tmp_path):
    export = make_export(tmp_path, [conversation("c1", "Hello", "2026-09-29T12:00:00Z")])
    result = run_collector("import_chats.py", args=(str(export),), env={"TZ": "America/New_York"})
    assert result.returncode == 0, result.stderr.decode()
    summary = json.loads(result.stdout)
    assert summary["ok"] and summary["imported"] == 1


def test_aggregator_counts_imported_chats(grid_home, tmp_path, new_york):
    import aggregate
    from datetime import date
    export = make_export(tmp_path, [conversation("c1", "Essay", "2026-09-29T15:00:00Z"),
                                    conversation("c2", "Recipes", "2026-09-29T16:00:00Z")])
    import_chats.import_export(str(export), ts=1)
    inputs = aggregate.load_inputs()
    _, details = aggregate.build(inputs, date(2026, 9, 30), aggregate.load_config(), generated_at=0)
    day = details["days"]["2026-09-29"]
    assert (day["sessions_chat"], day["sessions"]) == (2, 2)
    assert [c["title"] for c in day["chats"]] == ["Essay", "Recipes"]
