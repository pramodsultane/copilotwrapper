import json

import pytest

from copilotwrapper import compress


def test_small_messages_round_trip_unchanged():
    messages = [{"role": "user", "content": "hello"}]

    result = compress(messages)

    assert result.messages == messages
    assert result.tokens_saved == 0
    assert result.compression_ratio == 0.0
    assert result.transforms_applied == []


def test_large_json_payload_is_compressed():
    payload = json.dumps([
        {"id": index, "status": "active", "value": index * 7}
        for index in range(120)
    ])
    messages = [
        {"role": "user", "content": "summarize this"},
        {"role": "tool", "tool_call_id": "call_1", "content": payload},
    ]

    result = compress(messages)

    assert result.tokens_before > 0
    assert result.tokens_after <= result.tokens_before
    assert result.tokens_saved > 0
    assert result.messages != messages
    assert any(marker.startswith("json:") for marker in result.transforms_applied)
