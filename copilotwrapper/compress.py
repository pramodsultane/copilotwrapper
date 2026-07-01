from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass
class CompressResult:
    messages: list[dict[str, Any]]
    tokens_before: int = 0
    tokens_after: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 0.0
    transforms_applied: list[str] = field(default_factory=list)


def compress(messages: list[dict[str, Any]], min_tokens_to_compress: int = 250) -> CompressResult:
    if not messages:
        return CompressResult(messages=[])

    tokens_before = _count_tokens(messages)
    if tokens_before < min_tokens_to_compress:
        return CompressResult(messages=messages, tokens_before=tokens_before, tokens_after=tokens_before)

    compressed_messages = [_compress_message(message) for message in messages]
    tokens_after = _count_tokens(compressed_messages)

    if tokens_after >= tokens_before:
        return CompressResult(messages=messages, tokens_before=tokens_before, tokens_after=tokens_before)

    tokens_saved = tokens_before - tokens_after
    return CompressResult(
        messages=compressed_messages,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved=tokens_saved,
        compression_ratio=tokens_saved / tokens_before if tokens_before else 0.0,
        transforms_applied=["json:summary"],
    )


def _count_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        total += len(_TOKEN_PATTERN.findall(_message_text(message)))
    return total


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content is None:
        return json.dumps(message, sort_keys=True, separators=(",", ":"))
    if isinstance(content, str):
        return content
    return json.dumps(content, sort_keys=True, separators=(",", ":"))


def _compress_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, str):
        return dict(message)

    parsed = _parse_json(content)
    if isinstance(parsed, list):
        summary = _summarize_json_list(parsed)
        if summary is not None:
            compressed = dict(message)
            compressed["content"] = summary
            return compressed

    return dict(message)


def _parse_json(content: str) -> Any:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _summarize_json_list(items: list[Any]) -> str | None:
    if len(items) < 20:
        return None

    preview = items[:3]
    keys: list[str] = []
    if preview and all(isinstance(item, dict) for item in preview):
        seen: set[str] = set()
        for item in preview:
            for key in item.keys():
                if key not in seen:
                    seen.add(key)
                    keys.append(key)

    summary = {
        "kind": "json_list_summary",
        "item_count": len(items),
        "keys": keys,
        "preview": preview,
    }
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))