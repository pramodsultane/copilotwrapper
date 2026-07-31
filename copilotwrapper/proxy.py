from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import uuid
from typing import Any
from urllib.error import URLError

from .config import ProxyConfig
from .forwarder import forward_json
from .pipeline import rewrite_request_body
from .reversible_store import ReversibleStore

SUPPORTED_ENDPOINTS = {"/v1/chat/completions", "/v1/responses"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"transfer-encoding", "connection", "content-length"}


class _RequestBodyError(Exception):
    """Raised when the incoming request body cannot be read as configured.

    Carries the HTTP status code the proxy should respond with, so callers
    get a structured, accurate error instead of a misleading "invalid json".
    """

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def create_proxy_handler(config: ProxyConfig, store: ReversibleStore) -> type[BaseHTTPRequestHandler]:
    class ProxyHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            trace_id = str(uuid.uuid4())
            if self.path not in SUPPORTED_ENDPOINTS:
                self._write_json(404, {"error": {"message": "unsupported endpoint", "trace_id": trace_id}}, trace_id)
                return

            try:
                raw = self._read_request_bytes()
            except _RequestBodyError as exc:
                self._write_json(exc.status_code, {"error": {"message": exc.message, "trace_id": trace_id}}, trace_id)
                return

            try:
                body = json.loads(raw.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("request body must be a JSON object")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._write_json(400, {"error": {"message": "invalid json", "trace_id": trace_id}}, trace_id)
                return

            rewritten = rewrite_request_body(
                self.path,
                body,
                store=store,
                min_tokens_to_compress=config.min_tokens_to_compress,
                trace_id=trace_id,
            )

            try:
                upstream = forward_json(
                    self.path,
                    rewritten.body,
                    dict(self.headers.items()),
                    upstream_base_url=config.upstream_base_url,
                    timeout_seconds=config.request_timeout_seconds,
                )
            except TimeoutError:
                self._write_json(504, {"error": {"message": "upstream timeout", "trace_id": trace_id}}, trace_id)
                return
            except (URLError, OSError):
                self._write_json(502, {"error": {"message": "upstream transport error", "trace_id": trace_id}}, trace_id)
                return
            except ValueError:
                # Raised by the forwarder for a misconfigured upstream (bad scheme,
                # non path-only endpoint, etc.). Never let this propagate as an
                # unhandled server crash; report it as a structured 502 instead.
                self._write_json(
                    502,
                    {"error": {"message": "invalid upstream configuration", "trace_id": trace_id}},
                    trace_id,
                )
                return

            self.send_response(upstream.status_code)
            self.send_header("x-copilotwrapper-trace-id", trace_id)
            for key, value in upstream.headers.items():
                if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(upstream.body)

        def _write_json(self, status: int, payload: dict[str, Any], trace_id: str) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("x-copilotwrapper-trace-id", trace_id)
            self.end_headers()
            self.wfile.write(body)

        def _read_request_bytes(self) -> bytes:
            transfer_encoding = self.headers.get("transfer-encoding", "")
            codings = {coding.strip().lower() for coding in transfer_encoding.split(",") if coding.strip()}
            if "chunked" in codings:
                raise _RequestBodyError(501, "chunked request bodies are not supported")

            raw_length = self.headers.get("content-length")
            if raw_length is None:
                raise _RequestBodyError(411, "content-length header is required")
            try:
                length = int(raw_length)
            except ValueError:
                raise _RequestBodyError(400, "invalid content-length") from None
            if length < 0:
                raise _RequestBodyError(400, "negative content-length")
            if length > config.max_request_body_bytes:
                raise _RequestBodyError(
                    413,
                    f"request body exceeds maximum allowed size of {config.max_request_body_bytes} bytes",
                )
            return self.rfile.read(length)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return None

    return ProxyHandler


def run_proxy_server(config: ProxyConfig) -> None:
    store = ReversibleStore(config.store_path)
    handler = create_proxy_handler(config, store)
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), handler)
    server.serve_forever()
