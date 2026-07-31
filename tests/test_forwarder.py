from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from copilotwrapper.forwarder import forward_json


def test_forward_json_rejects_non_http_upstream() -> None:
    with pytest.raises(ValueError, match="http"):
        forward_json(
            "/v1/chat/completions",
            {"ok": True},
            {},
            upstream_base_url="file:///tmp/not-http",
            timeout_seconds=1.0,
        )


def test_forward_json_filters_hop_by_hop_headers_and_returns_response(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 201
        headers = {"X-Upstream": "ok", "Content-Type": "application/json"}

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def read(self) -> bytes:
            return b'{"ok":true}'

    def _fake_urlopen(req, timeout):  # noqa: ANN001, ANN202
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        captured["body"] = req.data
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("copilotwrapper.forwarder.urlopen", _fake_urlopen)

    out = forward_json(
        endpoint="/v1/chat/completions",
        payload={"ok": True},
        incoming_headers={
            "Authorization": "Bearer token",
            "Connection": "keep-alive",
            "Host": "ignored.example",
            "Content-Length": "123",
        },
        upstream_base_url="https://example.test/base",
        timeout_seconds=2.5,
    )

    assert out.status_code == 201
    assert out.body == b'{"ok":true}'
    assert out.headers == {"x-upstream": "ok", "content-type": "application/json"}

    assert captured["url"] == "https://example.test/base/v1/chat/completions"
    assert captured["method"] == "POST"
    assert captured["timeout"] == 2.5
    assert json.loads(captured["body"].decode("utf-8")) == {"ok": True}

    sent_headers = captured["headers"]
    assert sent_headers["authorization"] == "Bearer token"
    assert sent_headers["content-type"] == "application/json"
    assert "connection" not in sent_headers
    assert "host" not in sent_headers
    assert "content-length" not in sent_headers


def test_forward_json_does_not_allow_incoming_content_type_override(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            return False

        def read(self) -> bytes:
            return b"{}"

    def _fake_urlopen(req, timeout):  # noqa: ANN001, ANN202
        assert timeout == 1.0
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResponse()

    monkeypatch.setattr("copilotwrapper.forwarder.urlopen", _fake_urlopen)

    forward_json(
        endpoint="/v1/chat/completions",
        payload={"ok": True},
        incoming_headers={
            "Content-Type": "text/plain",
            "content-type": "application/x-www-form-urlencoded",
        },
        upstream_base_url="https://example.test/base",
        timeout_seconds=1.0,
    )

    sent_headers = captured["headers"]
    assert sent_headers["content-type"] == "application/json"


def test_forward_json_rejects_absolute_endpoint() -> None:
    with pytest.raises(ValueError, match="path-only"):
        forward_json(
            endpoint="https://attacker.test/override",
            payload={"ok": True},
            incoming_headers={},
            upstream_base_url="https://example.test/base",
            timeout_seconds=1.0,
        )


def test_forward_json_passes_through_http_error_response(monkeypatch) -> None:
    class _ErrorResponse:
        def __init__(self) -> None:
            self.status = 429
            self.headers = {"Retry-After": "1", "Content-Type": "application/json"}

        def read(self) -> bytes:
            return b'{"error":"rate limited"}'

        def close(self) -> None:
            return None

    def _fake_urlopen(_req, timeout):  # noqa: ANN001, ANN202
        assert timeout == 2.0
        raise HTTPError(
            url="https://example.test/base/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=_ErrorResponse().headers,
            fp=_ErrorResponse(),
        )

    monkeypatch.setattr("copilotwrapper.forwarder.urlopen", _fake_urlopen)

    out = forward_json(
        endpoint="/v1/chat/completions",
        payload={"ok": True},
        incoming_headers={},
        upstream_base_url="https://example.test/base",
        timeout_seconds=2.0,
    )

    assert out.status_code == 429
    assert out.headers == {"retry-after": "1", "content-type": "application/json"}
    assert out.body == b'{"error":"rate limited"}'
