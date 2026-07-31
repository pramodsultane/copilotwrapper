from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from copilotwrapper.config import ProxyConfig
from copilotwrapper.forwarder import UpstreamResponse
from copilotwrapper.pipeline import RewriteResult
from copilotwrapper.proxy import create_proxy_handler
from copilotwrapper.reversible_store import ReversibleStore


@dataclass
class _Response:
    status_code: int
    headers: dict[str, str]
    body: bytes


class _TestHttpClient:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def post(self, path: str, *, json_body: dict | None = None, data: bytes | None = None, headers: dict[str, str] | None = None) -> _Response:
        req_headers = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("content-type", "application/json")

        request = Request(
            url=f"{self._base_url}{path}",
            method="POST",
            data=data,
            headers=req_headers,
        )

        try:
            with urlopen(request, timeout=5.0) as response:
                return _Response(
                    status_code=response.status,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as error:
            return _Response(
                status_code=error.code,
                headers={k.lower(): v for k, v in (error.headers or {}).items()},
                body=error.read(),
            )


@pytest.fixture
def client(tmp_path):
    config = ProxyConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        upstream_base_url="https://upstream.test",
        min_tokens_to_compress=10,
        store_path=str(tmp_path / "store.jsonl"),
        request_timeout_seconds=1.0,
    )
    store = ReversibleStore(config.store_path)
    handler = create_proxy_handler(config, store)

    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer((config.listen_host, 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    try:
        yield _TestHttpClient(f"http://{host}:{port}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def raw_client(client):
    return client


def test_proxy_returns_404_for_unsupported_endpoint(client):
    resp = client.post("/v1/embeddings", json_body={"input": "x"})
    assert resp.status_code == 404
    body = json.loads(resp.body)
    assert body["error"]["message"] == "unsupported endpoint"
    assert body["error"]["trace_id"]


def test_proxy_returns_400_for_invalid_json(raw_client):
    resp = raw_client.post(
        "/v1/chat/completions",
        data=b"{bad",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body["error"]["message"] == "invalid json"
    assert body["error"]["trace_id"]


def test_proxy_forwards_rewritten_payload(monkeypatch, client):
    captured: dict[str, object] = {}

    def _fake_rewrite(endpoint, body, *, store, min_tokens_to_compress, trace_id):  # noqa: ANN001, ANN202
        _ = (store, min_tokens_to_compress)
        captured["rewrite_endpoint"] = endpoint
        captured["rewrite_body"] = body
        captured["trace_id"] = trace_id
        return RewriteResult(body={"rewritten": True}, transforms_applied=["x"], trace_id=trace_id)

    def _fake_forward(endpoint, payload, incoming_headers, *, upstream_base_url, timeout_seconds):  # noqa: ANN001, ANN202
        captured["forward_endpoint"] = endpoint
        captured["payload"] = payload
        captured["incoming_headers"] = incoming_headers
        captured["upstream_base_url"] = upstream_base_url
        captured["timeout_seconds"] = timeout_seconds
        return UpstreamResponse(
            status_code=201,
            headers={
                "content-type": "application/json",
                "x-upstream": "ok",
                "Connection": "keep-alive",
                "content-length": "999",
            },
            body=b'{"ok":true}',
        )

    monkeypatch.setattr("copilotwrapper.proxy.rewrite_request_body", _fake_rewrite)
    monkeypatch.setattr("copilotwrapper.proxy.forward_json", _fake_forward)

    resp = client.post(
        "/v1/chat/completions",
        json_body={"messages": []},
        headers={"authorization": "Bearer test"},
    )

    assert resp.status_code == 201
    assert json.loads(resp.body) == {"ok": True}
    assert resp.headers["x-upstream"] == "ok"
    assert resp.headers["x-copilotwrapper-trace-id"] == captured["trace_id"]
    assert "connection" not in resp.headers

    assert captured["rewrite_endpoint"] == "/v1/chat/completions"
    assert captured["rewrite_body"] == {"messages": []}
    assert captured["forward_endpoint"] == "/v1/chat/completions"
    assert captured["payload"] == {"rewritten": True}
    assert captured["upstream_base_url"] == "https://upstream.test"
    assert captured["timeout_seconds"] == 1.0
    assert captured["incoming_headers"]["Authorization"] == "Bearer test"


def test_proxy_returns_504_on_timeout(monkeypatch, client):
    def _fake_rewrite(endpoint, body, *, store, min_tokens_to_compress, trace_id):  # noqa: ANN001, ANN202
        _ = (endpoint, store, min_tokens_to_compress)
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    def _timeout(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise TimeoutError("timed out")

    monkeypatch.setattr("copilotwrapper.proxy.rewrite_request_body", _fake_rewrite)
    monkeypatch.setattr("copilotwrapper.proxy.forward_json", _timeout)

    resp = client.post("/v1/responses", json_body={"input": "x"})

    assert resp.status_code == 504
    body = json.loads(resp.body)
    assert body["error"]["message"] == "upstream timeout"
    assert body["error"]["trace_id"]
