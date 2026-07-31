from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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


@dataclass
class _MockUpstream:
    last_json_body: dict | None = None


def _raw_request(base_url: str, path: str, *, headers: dict[str, str], body: bytes = b"") -> _Response:
    """Send a request with full control over headers (e.g. omit content-length,
    or set Transfer-Encoding: chunked) which urllib.request cannot express.
    """
    parsed = urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5.0)
    try:
        conn.putrequest("POST", path, skip_host=False)
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.endheaders()
        if body:
            conn.send(body)
        response = conn.getresponse()
        return _Response(
            status_code=response.status,
            headers={k.lower(): v for k, v in response.getheaders()},
            body=response.read(),
        )
    finally:
        conn.close()


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

    def raw_post(self, path: str, *, headers: dict[str, str], body: bytes = b"") -> _Response:
        return _raw_request(self._base_url, path, headers=headers, body=body)



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


@pytest.fixture
def proxy_and_mock_upstream(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    upstream = _MockUpstream()

    class _MockUpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            raw_length = self.headers.get("content-length", "0")
            length = int(raw_length)
            payload = self.rfile.read(length) if length > 0 else b"{}"
            upstream.last_json_body = json.loads(payload.decode("utf-8"))

            body = b'{"id":"upstream-ok"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return None

    upstream_server = ThreadingHTTPServer(("127.0.0.1", 0), _MockUpstreamHandler)
    upstream_thread = Thread(target=upstream_server.serve_forever, daemon=True)
    upstream_thread.start()

    upstream_host, upstream_port = upstream_server.server_address
    config = ProxyConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        upstream_base_url=f"http://{upstream_host}:{upstream_port}",
        min_tokens_to_compress=10,
        store_path=str(tmp_path / "store.jsonl"),
        request_timeout_seconds=1.0,
    )
    store = ReversibleStore(config.store_path)
    handler = create_proxy_handler(config, store)
    proxy_server = ThreadingHTTPServer((config.listen_host, 0), handler)
    proxy_thread = Thread(target=proxy_server.serve_forever, daemon=True)
    proxy_thread.start()

    proxy_host, proxy_port = proxy_server.server_address
    try:
        yield _TestHttpClient(f"http://{proxy_host}:{proxy_port}"), upstream, store
    finally:
        proxy_server.shutdown()
        proxy_server.server_close()
        proxy_thread.join(timeout=5)
        upstream_server.shutdown()
        upstream_server.server_close()
        upstream_thread.join(timeout=5)


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


def test_proxy_returns_501_for_chunked_request_body(raw_client):
    resp = raw_client.raw_post(
        "/v1/chat/completions",
        headers={
            "content-type": "application/json",
            "transfer-encoding": "chunked",
        },
        body=b'11\r\n{"messages":[]}\r\n0\r\n\r\n',
    )
    assert resp.status_code == 501
    body = json.loads(resp.body)
    assert "chunked" in body["error"]["message"]
    assert body["error"]["trace_id"]


def test_proxy_returns_411_when_content_length_missing(raw_client):
    resp = raw_client.raw_post(
        "/v1/chat/completions",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 411
    body = json.loads(resp.body)
    assert "content-length" in body["error"]["message"]
    assert body["error"]["trace_id"]


def test_proxy_returns_413_when_body_exceeds_max_size(tmp_path):
    from http.server import ThreadingHTTPServer

    config = ProxyConfig(
        listen_host="127.0.0.1",
        listen_port=0,
        upstream_base_url="https://upstream.test",
        min_tokens_to_compress=10,
        store_path=str(tmp_path / "store.jsonl"),
        request_timeout_seconds=1.0,
        max_request_body_bytes=16,
    )
    store = ReversibleStore(config.store_path)
    handler = create_proxy_handler(config, store)
    server = ThreadingHTTPServer((config.listen_host, 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        oversized_client = _TestHttpClient(f"http://{host}:{port}")
        resp = oversized_client.post(
            "/v1/chat/completions",
            json_body={"messages": [{"role": "user", "content": "x" * 200}]},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert resp.status_code == 413
    body = json.loads(resp.body)
    assert "exceeds maximum" in body["error"]["message"]
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


def test_proxy_returns_502_on_upstream_transport_error(monkeypatch, client):
    def _fake_rewrite(endpoint, body, *, store, min_tokens_to_compress, trace_id):  # noqa: ANN001, ANN202
        _ = (endpoint, store, min_tokens_to_compress)
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    def _transport_error(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise URLError("connection reset")

    monkeypatch.setattr("copilotwrapper.proxy.rewrite_request_body", _fake_rewrite)
    monkeypatch.setattr("copilotwrapper.proxy.forward_json", _transport_error)

    resp = client.post("/v1/responses", json_body={"input": "x"})

    assert resp.status_code == 502
    body = json.loads(resp.body)
    assert body["error"]["message"] == "upstream transport error"
    assert body["error"]["trace_id"]


def test_proxy_returns_502_when_forwarder_raises_valueerror_for_misconfigured_upstream(monkeypatch, client):
    # Simulates a misconfigured upstream reaching the forwarder (e.g. bad scheme)
    # despite config-level validation; the proxy must respond with a structured
    # error rather than crashing the request thread.
    def _fake_rewrite(endpoint, body, *, store, min_tokens_to_compress, trace_id):  # noqa: ANN001, ANN202
        _ = (endpoint, store, min_tokens_to_compress)
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)

    def _bad_scheme(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ValueError("upstream_base_url must start with http:// or https://")

    monkeypatch.setattr("copilotwrapper.proxy.rewrite_request_body", _fake_rewrite)
    monkeypatch.setattr("copilotwrapper.proxy.forward_json", _bad_scheme)

    resp = client.post("/v1/responses", json_body={"input": "x"})

    assert resp.status_code == 502
    body = json.loads(resp.body)
    assert body["error"]["message"] == "invalid upstream configuration"
    assert body["error"]["trace_id"]


def test_proxy_forwards_rewritten_chat_payload(proxy_and_mock_upstream):
    client, upstream, store = proxy_and_mock_upstream
    original_tool_content = json.dumps([{"id": i, "status": "active"} for i in range(120)])
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "summarize"},
            {"role": "tool", "content": original_tool_content},
        ],
    }

    response = client.post("/v1/chat/completions", json_body=payload)

    assert response.status_code == 200
    assert json.loads(response.body) == {"id": "upstream-ok"}
    assert upstream.last_json_body is not None
    rewritten = upstream.last_json_body["messages"][1]["content"]
    parsed = json.loads(rewritten)
    assert parsed["kind"] == "json_list_summary"
    assert "reversible_handle" in parsed

    # The reversible promise: the handle emitted to upstream must resolve back
    # to the exact original (pre-compression) content via ReversibleStore.get.
    handle = parsed["reversible_handle"]
    stored_row = store.get(handle)
    assert stored_row is not None
    assert stored_row["payload"] == original_tool_content


def test_proxy_forwards_responses_payload_without_user_text_rewrite(proxy_and_mock_upstream):
    client, upstream, _store = proxy_and_mock_upstream
    payload = {
        "model": "gpt-4.1",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "do not change me"}]}],
    }
    expected = json.loads(json.dumps(payload))

    response = client.post("/v1/responses", json_body=payload)

    assert response.status_code == 200
    assert json.loads(response.body) == {"id": "upstream-ok"}
    assert upstream.last_json_body == expected
