from __future__ import annotations

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
