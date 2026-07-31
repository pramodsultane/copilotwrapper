import json

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
