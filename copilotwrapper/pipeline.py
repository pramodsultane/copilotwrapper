from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .compress import compress
from .reversible_store import ReversibleStore


@dataclass
class RewriteResult:
    body: dict[str, Any]
    transforms_applied: list[str]
    trace_id: str


def rewrite_request_body(
    endpoint: str,
    body: dict[str, Any],
    *,
    store: ReversibleStore,
    min_tokens_to_compress: int,
    trace_id: str,
) -> RewriteResult:
    if endpoint == "/v1/chat/completions":
        return _rewrite_chat(
            body,
            store=store,
            min_tokens_to_compress=min_tokens_to_compress,
            trace_id=trace_id,
        )
    if endpoint == "/v1/responses":
        return _rewrite_responses(
            body,
            store=store,
            min_tokens_to_compress=min_tokens_to_compress,
            trace_id=trace_id,
        )
    return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)


def _rewrite_chat(
    body: dict[str, Any],
    *,
    store: ReversibleStore,
    min_tokens_to_compress: int,
    trace_id: str,
) -> RewriteResult:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    result = compress(messages, min_tokens_to_compress=min_tokens_to_compress)
    rewritten = dict(body)
    rewritten["messages"] = _attach_handles(
        result.messages,
        messages,
        store=store,
        trace_id=trace_id,
        segment_root="messages",
    )
    return RewriteResult(
        body=rewritten,
        transforms_applied=result.transforms_applied,
        trace_id=trace_id,
    )


def _rewrite_responses(
    body: dict[str, Any],
    *,
    store: ReversibleStore,
    min_tokens_to_compress: int,
    trace_id: str,
) -> RewriteResult:
    _ = (store, min_tokens_to_compress)
    return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)


def _attach_handles(
    new_messages: list[dict[str, Any]],
    old_messages: list[dict[str, Any]],
    *,
    store: ReversibleStore,
    trace_id: str,
    segment_root: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, (new_msg, old_msg) in enumerate(zip(new_messages, old_messages)):
        old_content = old_msg.get("content")
        new_content = new_msg.get("content")
        if isinstance(old_content, str) and isinstance(new_content, str) and new_content != old_content:
            handle = _make_handle(trace_id, segment_root, index, old_content)
            store.put(handle, old_content, trace_id, f"{segment_root}[{index}].content")

            parsed = json.loads(new_content)
            parsed["reversible_handle"] = handle

            patched = dict(new_msg)
            patched["content"] = json.dumps(parsed, separators=(",", ":"), sort_keys=True)
            out.append(patched)
        else:
            out.append(new_msg)
    return out


def _make_handle(trace_id: str, segment_root: str, index: int, original: str) -> str:
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    return f"cw:{trace_id}:{segment_root}:{index}:{digest}"
