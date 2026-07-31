from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
from typing import Any

from .compress import compress
from .reversible_store import ReversibleStore

_LOGGER = logging.getLogger(__name__)


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
    _log_fallback("unsupported_endpoint_passthrough", endpoint=endpoint, trace_id=trace_id)
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
        _log_fallback("chat_messages_not_list", endpoint="/v1/chat/completions", trace_id=trace_id)
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            _log_fallback(
                "chat_messages_non_object_entry",
                endpoint="/v1/chat/completions",
                trace_id=trace_id,
                index=index,
                entry_type=type(message).__name__,
            )
            return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    tool_indexes = [index for index, message in enumerate(messages) if _is_tool_style_message(message)]
    if not tool_indexes:
        _log_fallback("chat_no_tool_style_messages", endpoint="/v1/chat/completions", trace_id=trace_id)
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    tool_messages = [messages[index] for index in tool_indexes]
    try:
        result = compress(tool_messages, min_tokens_to_compress=min_tokens_to_compress)
    except (AttributeError, TypeError, ValueError) as exc:
        _log_fallback(
            "chat_compress_failure",
            endpoint="/v1/chat/completions",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    rewritten = dict(body)
    merged_messages = [dict(message) for message in messages]
    for offset, index in enumerate(tool_indexes):
        merged_messages[index] = result.messages[offset]

    try:
        rewritten["messages"] = _attach_handles(
            merged_messages,
            messages,
            store=store,
            trace_id=trace_id,
            segment_root="messages",
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        _log_fallback(
            "chat_attach_handle_failure",
            endpoint="/v1/chat/completions",
            trace_id=trace_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)
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
    _log_fallback("responses_passthrough_conservative", endpoint="/v1/responses", trace_id=trace_id)
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
        if not _is_tool_style_message(old_msg):
            out.append(new_msg)
            continue

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


def _is_tool_style_message(message: dict[str, Any]) -> bool:
    role = message.get("role")
    if role == "tool":
        return True
    tool_call_id = message.get("tool_call_id")
    return isinstance(tool_call_id, str) and bool(tool_call_id)


def _log_fallback(reason: str, *, endpoint: str, trace_id: str, **details: Any) -> None:
    extras = " ".join(f"{key}={details[key]}" for key in sorted(details))
    if extras:
        _LOGGER.warning(
            "pipeline_fallback reason=%s endpoint=%s trace_id=%s %s",
            reason,
            endpoint,
            trace_id,
            extras,
        )
    else:
        _LOGGER.warning(
            "pipeline_fallback reason=%s endpoint=%s trace_id=%s",
            reason,
            endpoint,
            trace_id,
        )


def _make_handle(trace_id: str, segment_root: str, index: int, original: str) -> str:
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    return f"cw:{trace_id}:{segment_root}:{index}:{digest}"
