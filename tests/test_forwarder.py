from __future__ import annotations

import json

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
