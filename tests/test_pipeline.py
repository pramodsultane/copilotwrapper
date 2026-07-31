import json
import logging

import copilotwrapper.pipeline as pipeline
from copilotwrapper.pipeline import rewrite_request_body
from copilotwrapper.reversible_store import ReversibleStore


def test_rewrite_chat_messages_large_tool_json(tmp_path):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "tool", "content": json.dumps([{"id": i, "value": i} for i in range(120)])},
        ],
    }
    out = rewrite_request_body(
        "/v1/chat/completions",
        body,
        store=store,
        min_tokens_to_compress=20,
        trace_id="trace-1",
    )
    content = out.body["messages"][1]["content"]
    parsed = json.loads(content)
    assert parsed["kind"] == "json_list_summary"
    assert "reversible_handle" in parsed


def test_rewrite_responses_input_preserves_plain_user_text(tmp_path):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {
        "model": "gpt-4.1",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "do not change me"}]}],
    }
    out = rewrite_request_body(
        "/v1/responses",
        body,
        store=store,
        min_tokens_to_compress=20,
        trace_id="trace-2",
    )
    assert out.body == body
    assert out.transforms_applied == []


def test_rewrite_responses_logs_conservative_passthrough_reason(tmp_path, caplog):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {"model": "gpt-4.1", "input": [{"role": "user", "content": "hi"}]}
    with caplog.at_level(logging.WARNING, logger="copilotwrapper.pipeline"):
        out = rewrite_request_body(
            "/v1/responses",
            body,
            store=store,
            min_tokens_to_compress=20,
            trace_id="trace-2b",
        )
    assert out.body == body
    assert out.transforms_applied == []
    assert "pipeline_fallback reason=responses_passthrough_conservative" in caplog.text


def test_chat_rewrite_does_not_compress_non_tool_user_json(tmp_path):
    store = ReversibleStore(tmp_path / "s.jsonl")
    original_content = json.dumps([{"id": i, "value": i} for i in range(120)])
    body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": original_content},
        ],
    }
    out = rewrite_request_body(
        "/v1/chat/completions",
        body,
        store=store,
        min_tokens_to_compress=20,
        trace_id="trace-3",
    )
    assert out.body == body
    assert out.transforms_applied == []


def test_chat_rewrite_malformed_message_entries_fail_open_with_reason_log(tmp_path, caplog):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "tool", "content": json.dumps([{"id": i} for i in range(40)])},
            "bad-entry",
        ],
    }
    with caplog.at_level(logging.WARNING, logger="copilotwrapper.pipeline"):
        out = rewrite_request_body(
            "/v1/chat/completions",
            body,
            store=store,
            min_tokens_to_compress=20,
            trace_id="trace-4",
        )
    assert out.body == body
    assert out.transforms_applied == []
    assert "pipeline_fallback reason=chat_messages_non_object_entry" in caplog.text


def test_chat_rewrite_attach_handle_failure_falls_back_with_reason_log(tmp_path, caplog, monkeypatch):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "tool", "content": json.dumps([{"id": i} for i in range(40)])}],
    }

    def _broken_attach(*args, **kwargs):  # noqa: ANN002, ANN003
        raise ValueError("boom")

    monkeypatch.setattr(pipeline, "_attach_handles", _broken_attach)

    with caplog.at_level(logging.WARNING, logger="copilotwrapper.pipeline"):
        out = rewrite_request_body(
            "/v1/chat/completions",
            body,
            store=store,
            min_tokens_to_compress=20,
            trace_id="trace-5",
        )

    assert out.body == body
    assert out.transforms_applied == []
    assert "pipeline_fallback reason=chat_attach_handle_failure" in caplog.text


def test_chat_rewrite_store_put_failure_falls_back_with_reason_log(tmp_path, caplog, monkeypatch):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {
        "model": "gpt-4o",
        "messages": [{"role": "tool", "content": json.dumps([{"id": i} for i in range(40)])}],
    }

    def _broken_put(*args, **kwargs):  # noqa: ANN002, ANN003
        raise OSError("disk full")

    monkeypatch.setattr(store, "put", _broken_put)

    with caplog.at_level(logging.WARNING, logger="copilotwrapper.pipeline"):
        out = rewrite_request_body(
            "/v1/chat/completions",
            body,
            store=store,
            min_tokens_to_compress=20,
            trace_id="trace-5b",
        )

    assert out.body == body
    assert out.transforms_applied == []
    assert "pipeline_fallback reason=chat_store_write_failure" in caplog.text


def test_unsupported_endpoint_logs_passthrough_reason(tmp_path, caplog):
    store = ReversibleStore(tmp_path / "s.jsonl")
    body = {"k": "v"}
    with caplog.at_level(logging.WARNING, logger="copilotwrapper.pipeline"):
        out = rewrite_request_body(
            "/v1/embeddings",
            body,
            store=store,
            min_tokens_to_compress=20,
            trace_id="trace-6",
        )
    assert out.body == body
    assert out.transforms_applied == []
    assert "pipeline_fallback reason=unsupported_endpoint_passthrough" in caplog.text
