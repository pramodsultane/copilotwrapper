from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

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


def test_put_writes_jsonl_row_in_single_write_call(tmp_path, monkeypatch) -> None:
    store = ReversibleStore(tmp_path / "store.jsonl")

    writes: list[str] = []

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def write(self, chunk: str) -> int:
            writes.append(chunk)
            return len(chunk)

    def _fake_open(self: Path, mode: str = "r", encoding: str | None = None):  # noqa: ARG001
        assert mode == "a"
        return _FakeFile()

    monkeypatch.setattr(Path, "open", _fake_open)

    store.put("cw:test:single-write", {"k": "v"}, "trace-1", "messages[1].content")

    assert len(writes) == 1
    assert writes[0].endswith("\n")


def test_put_is_thread_safe_across_store_instances_with_same_path(tmp_path, monkeypatch) -> None:
    store_path = tmp_path / "store.jsonl"
    store_a = ReversibleStore(store_path)
    store_b = ReversibleStore(store_path)

    writes: list[str] = []
    active_writes = 0
    max_active_writes = 0
    state_lock = threading.Lock()
    barrier = threading.Barrier(8)

    class _FakeFile:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def write(self, chunk: str) -> int:
            nonlocal active_writes, max_active_writes
            with state_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
            time.sleep(0.002)
            writes.append(chunk)
            with state_lock:
                active_writes -= 1
            return len(chunk)

    def _fake_open(self: Path, mode: str = "r", encoding: str | None = None):  # noqa: ARG001
        assert mode == "a"
        return _FakeFile()

    monkeypatch.setattr(Path, "open", _fake_open)

    def _worker(index: int) -> None:
        barrier.wait()
        store = store_a if index % 2 == 0 else store_b
        store.put(f"cw:test:{index}", {"i": index}, f"trace-{index}", f"messages[{index}]")

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active_writes == 1
    assert len(writes) == 8
