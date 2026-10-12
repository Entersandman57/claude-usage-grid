import json
import os
import struct
from compression import zstd

import app_scan
from conftest import all_text

ORG = "11111111-1111-4111-8111-111111111111"
A, B, C = ("aaaaaaaa-aaaa-4aaa-8aaa-%012d" % i for i in range(3))


def entry(url, body, encoding="zstd"):
    """A Chromium simple-cache entry file (header, key, body, EOF, headers, EOF)."""
    key = ("1/0/" + url).encode()
    data = json.dumps(body).encode()
    if encoding == "zstd":
        data = zstd.compress(data)
    headers = b"HTTP/1.1 200\x00content-type: application/json\x00"
    headers += (b"content-encoding: %s\x00" % encoding.encode() if encoding else b"") + b"\x00"
    eof = lambda size: struct.pack("<QIII4x", app_scan.EOF_MAGIC, 0, 0, size)
    return (struct.pack("<QIIII", app_scan.ENTRY_MAGIC, 5, len(key), 0, 0) + key + data
            + eof(0) + headers + eof(len(headers)))


def make_app(tmp_path, files, history=None):
    app = tmp_path / "Claude"
    cache = app / "Cache" / "Cache_Data"
    cache.mkdir(parents=True)
    for i, (url, body) in enumerate(files):
        (cache / ("%016x_0" % i)).write_bytes(entry(url, body))
    (cache / "index").write_bytes(b"not an entry")
    if history is not None:
        (app / "plan-usage-history.json").write_text(json.dumps(history))
    return app


LIST = "https://claude.ai/api/organizations/%s/chat_conversations_v2?limit=30&starred=false" % ORG


def listed(uuid, created, last, **extra):
    item = {"uuid": uuid, "name": "Title " + uuid[-1], "summary": "SECRETSUMMARY", "created_at": created,
            "updated_at": last, "latest_assistant_output_at": last, "has_assistant_outputs": True}
    item.update(extra)
    return item


def scan(monkeypatch, app):
    monkeypatch.setenv("CLAUDE_USAGE_GRID_APP_DIR", str(app))
    assert app_scan.main([]) == 0


def test_chats_come_from_cached_lists_and_conversations(tmp_path, grid_home, monkeypatch, new_york):
    app = make_app(tmp_path, [
        (LIST, {"data": [listed(A, "2026-10-09T15:00:00Z", "2026-10-11T15:00:00Z"),
                         listed(B, "2026-10-11T15:00:00Z", "2026-10-11T15:00:00Z", has_assistant_outputs=False)],
                "has_more": True}),
        ("https://claude.ai/api/organizations/%s/chat_conversations/%s?tree=True" % (ORG, C),
         {"uuid": C, "name": "Opened", "chat_messages": [
             {"created_at": "2026-10-10T03:00:00Z", "text": "SECRETTEXT"},   # Oct 9, 11 PM in New York
             {"created_at": "2026-10-10T16:00:00Z", "text": "SECRETTEXT"}]}),
        ("https://claude.ai/api/organizations/%s/account" % ORG, {"email": "SECRETEMAIL"}),
    ])
    before = sorted((p, os.path.getmtime(os.path.join(r, p))) for r, _, fs in os.walk(app) for p in fs)
    scan(monkeypatch, app)
    chats = json.loads((grid_home / "app-chats.json").read_text())["chats"]
    assert chats == {A: {"uuid": A, "title": "Title 0", "days": ["2026-10-09", "2026-10-11"]},
                     C: {"uuid": C, "title": "Opened", "days": ["2026-10-09", "2026-10-10"]}}
    text = all_text(grid_home)
    assert "SECRET" not in text
    after = sorted((p, os.path.getmtime(os.path.join(r, p))) for r, _, fs in os.walk(app) for p in fs)
    assert before == after  # the app's folder is never written


def test_rescans_add_new_days_only(tmp_path, grid_home, monkeypatch, new_york, capsys):
    app = make_app(tmp_path, [(LIST, {"data": [listed(A, "2026-10-09T15:00:00Z", "2026-10-09T15:00:00Z")]})])
    scan(monkeypatch, app)
    scan(monkeypatch, app)
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["new_chat_days"] == 0
    app2 = make_app(tmp_path / "later", [(LIST, {"data": [listed(A, "2026-10-09T15:00:00Z", "2026-10-12T15:00:00Z")]})])
    scan(monkeypatch, app2)
    chats = json.loads((grid_home / "app-chats.json").read_text())["chats"]
    assert chats[A]["days"] == ["2026-10-09", "2026-10-12"]  # the day seen earlier is kept


def test_usage_history_becomes_readings_once(tmp_path, grid_home, monkeypatch):
    history = {"version": 2, "samples": [{"org": ORG, "t": 1790000000000, "u": {"fh": 28, "sd": 11}},
                                         {"org": ORG, "t": 1790000900000, "u": {"fh": 31, "sd": 12, "xu": 0}},
                                         {"org": ORG, "t": 1790001800000, "u": {"fh": "x"}}]}
    app = make_app(tmp_path, [], history)
    scan(monkeypatch, app)
    scan(monkeypatch, app)
    readings = [json.loads(line) for line in (grid_home / "readings.jsonl").read_text().splitlines()]
    assert [(r["ts"], r["source"], r["five_hour"], r["seven_day"]["used_percentage"]) for r in readings] == [
        (1790000000.0, "app_history", {"used_percentage": 28.0, "resets_at": None}, 11.0),
        (1790000900.0, "app_history", {"used_percentage": 31.0, "resets_at": None}, 12.0)]


def test_missing_app_folder_is_fine(tmp_path, grid_home, monkeypatch, capsys):
    scan(monkeypatch, tmp_path / "nowhere")
    assert json.loads(capsys.readouterr().out) == {"ok": True, "chats_seen": 0, "new_chat_days": 0,
                                                   "history_samples": 0, "error": None}
