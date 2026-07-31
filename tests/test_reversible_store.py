from __future__ import annotations

import logging

from copilotwrapper.reversible_store import ReversibleStore


def test_put_and_get_round_trip(tmp_path) -> None:
    store = ReversibleStore(tmp_path / "store.jsonl")

    store.put("cw:test:1", {"k": "v"}, "trace-1", "messages[1].content")

    row = store.get("cw:test:1")
    assert row is not None
    assert row["handle"] == "cw:test:1"
    assert row["payload"] == {"k": "v"}
    assert row["trace_id"] == "trace-1"
    assert row["segment_path"] == "messages[1].content"
    assert isinstance(row["created_at"], float)


def test_get_returns_none_for_missing_handle(tmp_path) -> None:
    store = ReversibleStore(tmp_path / "store.jsonl")

    assert store.get("cw:missing") is None


def test_get_skips_malformed_jsonl_lines_with_structured_log(tmp_path, caplog) -> None:
    store_path = tmp_path / "store.jsonl"
    store_path.write_text(
        '{"handle":"cw:bad","payload":\n'
        '{"handle":"cw:good","payload":{"k":"v"},"trace_id":"trace-1","segment_path":"messages[1].content","created_at":1.0}\n',
        encoding="utf-8",
    )
    store = ReversibleStore(store_path)

    with caplog.at_level(logging.WARNING, logger="copilotwrapper.reversible_store"):
        row = store.get("cw:good")

    assert row is not None
    assert row["handle"] == "cw:good"
    assert "reversible_store_malformed_jsonl_line path=" in caplog.text
