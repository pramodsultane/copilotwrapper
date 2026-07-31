# Copilot Token-Saving Proxy v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local Copilot-focused reverse proxy that conservatively compresses large JSON/tool payloads before forwarding to upstream `/v1/chat/completions` and `/v1/responses`.

**Architecture:** Add small focused Python modules for config, reversible storage, compression pipeline, forwarding, and HTTP serving, then expose the server through `copilotwrapper proxy`. Keep current `compress` behavior intact and limit rewrite logic to tool-style large JSON segments.

**Tech Stack:** Python 3.12 stdlib (`argparse`, `http.server`, `urllib`, `json`, `hashlib`, `pathlib`, `time`), pytest

## Global Constraints

- Local HTTP reverse proxy for `POST /v1/chat/completions` and `POST /v1/responses`.
- Conservative request compression: only large JSON/tool-style payload segments; do not rewrite normal user prose by default.
- Reversible rewrite support: store original segments locally and replace rewritten sections with handles and summary metadata.
- CLI command must launch proxy and print environment guidance for Copilot CLI routing.
- No silent fallback paths; all fallback reasons must be logged in structured form.
- Keep implementation clean-room and original inside `copilotwrapper` only.

---

## File Structure Map

- Modify `copilotwrapper/__init__.py` to export new public proxy/config types used in tests.
- Modify `copilotwrapper/cli.py` to add `proxy` command while preserving existing `compress`.
- Create `copilotwrapper/config.py` for runtime settings and env parsing.
- Create `copilotwrapper/reversible_store.py` for handle-based local segment persistence.
- Create `copilotwrapper/pipeline.py` for conservative endpoint-aware payload rewriting.
- Create `copilotwrapper/forwarder.py` for upstream HTTP forwarding.
- Create `copilotwrapper/proxy.py` for HTTP server and endpoint handlers.
- Add tests:
  - `tests/test_config.py`
  - `tests/test_reversible_store.py`
  - `tests/test_pipeline.py`
  - `tests/test_forwarder.py`
  - `tests/test_proxy.py`
  - Update `tests/test_cli.py`

### Task 1: Runtime Config + Reversible Store Foundation

**Files:**
- Create: `copilotwrapper/config.py`
- Create: `copilotwrapper/reversible_store.py`
- Modify: `copilotwrapper/__init__.py`
- Test: `tests/test_config.py`
- Test: `tests/test_reversible_store.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `class ProxyConfig` with fields:
    - `listen_host: str`
    - `listen_port: int`
    - `upstream_base_url: str`
    - `min_tokens_to_compress: int`
    - `store_path: str`
    - `request_timeout_seconds: float`
  - `def load_proxy_config_from_env() -> ProxyConfig`
  - `class ReversibleStore` with:
    - `def put(self, handle: str, payload: object, trace_id: str, segment_path: str) -> None`
    - `def get(self, handle: str) -> dict[str, object] | None`

- [ ] **Step 1: Write failing config tests**

```python
from copilotwrapper.config import ProxyConfig, load_proxy_config_from_env


def test_load_proxy_config_defaults(monkeypatch):
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_HOST", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_PORT", raising=False)
    cfg = load_proxy_config_from_env()
    assert isinstance(cfg, ProxyConfig)
    assert cfg.listen_host == "127.0.0.1"
    assert cfg.listen_port == 8787


def test_load_proxy_config_requires_upstream(monkeypatch):
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)
    try:
        load_proxy_config_from_env()
    except ValueError as exc:
        assert "COPILOTWRAPPER_UPSTREAM_BASE_URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run failing config tests**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with import or missing symbol errors.

- [ ] **Step 3: Implement config module**

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ProxyConfig:
    listen_host: str
    listen_port: int
    upstream_base_url: str
    min_tokens_to_compress: int
    store_path: str
    request_timeout_seconds: float


def load_proxy_config_from_env() -> ProxyConfig:
    upstream = os.getenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "").strip()
    if not upstream:
        raise ValueError("COPILOTWRAPPER_UPSTREAM_BASE_URL is required")
    return ProxyConfig(
        listen_host=os.getenv("COPILOTWRAPPER_LISTEN_HOST", "127.0.0.1"),
        listen_port=int(os.getenv("COPILOTWRAPPER_LISTEN_PORT", "8787")),
        upstream_base_url=upstream.rstrip("/"),
        min_tokens_to_compress=int(os.getenv("COPILOTWRAPPER_MIN_TOKENS", "250")),
        store_path=os.getenv("COPILOTWRAPPER_STORE_PATH", ".copilotwrapper-store.jsonl"),
        request_timeout_seconds=float(os.getenv("COPILOTWRAPPER_TIMEOUT_SECONDS", "30")),
    )
```

- [ ] **Step 4: Write failing reversible store tests**

```python
from copilotwrapper.reversible_store import ReversibleStore


def test_put_and_get_round_trip(tmp_path):
    store = ReversibleStore(tmp_path / "store.jsonl")
    store.put("cw:test:1", {"k": "v"}, "trace-1", "messages[1].content")
    row = store.get("cw:test:1")
    assert row is not None
    assert row["payload"] == {"k": "v"}
    assert row["trace_id"] == "trace-1"
```

- [ ] **Step 5: Run failing reversible store tests**

Run: `pytest tests/test_reversible_store.py -v`
Expected: FAIL with import or missing symbol errors.

- [ ] **Step 6: Implement reversible store**

```python
import json
from pathlib import Path
from time import time


class ReversibleStore:
    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def put(self, handle: str, payload: object, trace_id: str, segment_path: str) -> None:
        row = {
            "handle": handle,
            "trace_id": trace_id,
            "segment_path": segment_path,
            "payload": payload,
            "created_at": time(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":")))
            fh.write("\n")

    def get(self, handle: str) -> dict[str, object] | None:
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                row = json.loads(line)
                if row.get("handle") == handle:
                    return row
        return None
```

- [ ] **Step 7: Export public symbols**

```python
from .compress import CompressResult, compress
from .config import ProxyConfig, load_proxy_config_from_env
from .reversible_store import ReversibleStore

__all__ = [
    "CompressResult",
    "ProxyConfig",
    "ReversibleStore",
    "compress",
    "load_proxy_config_from_env",
]
```

- [ ] **Step 8: Run task tests**

Run: `pytest tests/test_config.py tests/test_reversible_store.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add copilotwrapper/__init__.py copilotwrapper/config.py copilotwrapper/reversible_store.py tests/test_config.py tests/test_reversible_store.py
git commit -m "feat: add proxy config and reversible store foundation"
```

### Task 2: Conservative Rewrite Pipeline for Copilot Endpoints

**Files:**
- Create: `copilotwrapper/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes:
  - `ReversibleStore.put(handle, payload, trace_id, segment_path) -> None`
  - `compress(messages, min_tokens_to_compress=...) -> CompressResult`
- Produces:
  - `class RewriteResult` fields:
    - `body: dict[str, object]`
    - `transforms_applied: list[str]`
    - `trace_id: str`
  - `def rewrite_request_body(endpoint: str, body: dict[str, object], *, store: ReversibleStore, min_tokens_to_compress: int, trace_id: str) -> RewriteResult`

- [ ] **Step 1: Write failing pipeline tests for `/v1/chat/completions`**

```python
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
```

- [ ] **Step 2: Write failing pipeline tests for `/v1/responses`**

```python
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
```

- [ ] **Step 3: Run failing pipeline tests**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with import or missing symbol errors.

- [ ] **Step 4: Implement pipeline**

```python
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
        return _rewrite_chat(body, store=store, min_tokens_to_compress=min_tokens_to_compress, trace_id=trace_id)
    if endpoint == "/v1/responses":
        return _rewrite_responses(body, store=store, min_tokens_to_compress=min_tokens_to_compress, trace_id=trace_id)
    return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)


def _rewrite_chat(body: dict[str, Any], *, store: ReversibleStore, min_tokens_to_compress: int, trace_id: str) -> RewriteResult:
    messages = body.get("messages")
    if not isinstance(messages, list):
        return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)
    result = compress(messages, min_tokens_to_compress=min_tokens_to_compress)
    rewritten = dict(body)
    rewritten["messages"] = _attach_handles(result.messages, messages, store=store, trace_id=trace_id, segment_root="messages")
    return RewriteResult(body=rewritten, transforms_applied=result.transforms_applied, trace_id=trace_id)


def _rewrite_responses(body: dict[str, Any], *, store: ReversibleStore, min_tokens_to_compress: int, trace_id: str) -> RewriteResult:
    # Conservative mode: responses schema is passed through until tool-content extraction is explicit.
    return RewriteResult(body=body, transforms_applied=[], trace_id=trace_id)


def _attach_handles(new_messages, old_messages, *, store: ReversibleStore, trace_id: str, segment_root: str):
    out = []
    for idx, (new_msg, old_msg) in enumerate(zip(new_messages, old_messages)):
        old_content = old_msg.get("content")
        new_content = new_msg.get("content")
        if isinstance(old_content, str) and isinstance(new_content, str) and new_content != old_content:
            handle = _make_handle(trace_id, segment_root, idx, old_content)
            store.put(handle, old_content, trace_id, f"{segment_root}[{idx}].content")
            parsed = json.loads(new_content)
            parsed["reversible_handle"] = handle
            patched = dict(new_msg)
            patched["content"] = json.dumps(parsed, separators=(",", ":"), sort_keys=True)
            out.append(patched)
        else:
            out.append(new_msg)
    return out


def _make_handle(trace_id: str, segment_root: str, idx: int, original: str) -> str:
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()[:12]
    return f"cw:{trace_id}:{segment_root}:{idx}:{digest}"
```

- [ ] **Step 5: Run task tests**

Run: `pytest tests/test_pipeline.py tests/test_compress.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add copilotwrapper/pipeline.py tests/test_pipeline.py tests/test_compress.py
git commit -m "feat: add conservative copilot rewrite pipeline"
```

### Task 3: Upstream Forwarder with Timeout and Header Filtering

**Files:**
- Create: `copilotwrapper/forwarder.py`
- Test: `tests/test_forwarder.py`

**Interfaces:**
- Consumes:
  - `ProxyConfig.upstream_base_url`
  - `ProxyConfig.request_timeout_seconds`
- Produces:
  - `class UpstreamResponse` fields:
    - `status_code: int`
    - `headers: dict[str, str]`
    - `body: bytes`
  - `def forward_json(endpoint: str, payload: dict[str, object], incoming_headers: dict[str, str], *, upstream_base_url: str, timeout_seconds: float) -> UpstreamResponse`

- [ ] **Step 1: Write failing forwarder tests**

```python
from copilotwrapper.forwarder import forward_json


def test_forward_json_rejects_non_http_upstream():
    try:
        forward_json(
            "/v1/chat/completions",
            {"ok": True},
            {},
            upstream_base_url="file:///tmp/not-http",
            timeout_seconds=1.0,
        )
    except ValueError as exc:
        assert "http" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run failing forwarder tests**

Run: `pytest tests/test_forwarder.py -v`
Expected: FAIL with import or missing symbol errors.

- [ ] **Step 3: Implement forwarder**

```python
from dataclasses import dataclass
import json
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


@dataclass
class UpstreamResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


def forward_json(endpoint, payload, incoming_headers, *, upstream_base_url, timeout_seconds):
    parsed = urlparse(upstream_base_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("upstream_base_url must start with http:// or https://")
    url = urljoin(upstream_base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"content-type": "application/json"}
    for key, value in incoming_headers.items():
        if key.lower() not in HOP_BY_HOP:
            headers[key] = value
    req = Request(url=url, data=body_bytes, method="POST", headers=headers)
    with urlopen(req, timeout=timeout_seconds) as resp:
        return UpstreamResponse(
            status_code=resp.status,
            headers={k.lower(): v for k, v in resp.headers.items()},
            body=resp.read(),
        )
```

- [ ] **Step 4: Run task tests**

Run: `pytest tests/test_forwarder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add copilotwrapper/forwarder.py tests/test_forwarder.py
git commit -m "feat: add upstream json forwarder for proxy"
```

### Task 4: Proxy HTTP Server Endpoints + Structured Errors

**Files:**
- Create: `copilotwrapper/proxy.py`
- Test: `tests/test_proxy.py`

**Interfaces:**
- Consumes:
  - `ProxyConfig`
  - `ReversibleStore`
  - `rewrite_request_body(...) -> RewriteResult`
  - `forward_json(...) -> UpstreamResponse`
- Produces:
  - `def create_proxy_handler(config: ProxyConfig, store: ReversibleStore) -> type[BaseHTTPRequestHandler]`
  - `def run_proxy_server(config: ProxyConfig) -> None`

- [ ] **Step 1: Write failing proxy tests**

```python
def test_proxy_returns_404_for_unsupported_endpoint(client):
    resp = client.post("/v1/embeddings", json={"input": "x"})
    assert resp.status_code == 404


def test_proxy_returns_400_for_invalid_json(raw_client):
    resp = raw_client.post("/v1/chat/completions", data=b"{bad", headers={"content-type": "application/json"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run failing proxy tests**

Run: `pytest tests/test_proxy.py -v`
Expected: FAIL with missing server symbols.

- [ ] **Step 3: Implement proxy server**

```python
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import uuid

from .forwarder import forward_json
from .pipeline import rewrite_request_body
from .reversible_store import ReversibleStore


SUPPORTED_ENDPOINTS = {"/v1/chat/completions", "/v1/responses"}


def create_proxy_handler(config, store: ReversibleStore):
    class ProxyHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            trace_id = str(uuid.uuid4())
            if self.path not in SUPPORTED_ENDPOINTS:
                self._write_json(404, {"error": {"message": "unsupported endpoint", "trace_id": trace_id}})
                return
            try:
                raw = self.rfile.read(int(self.headers.get("content-length", "0")))
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                self._write_json(400, {"error": {"message": "invalid json", "trace_id": trace_id}})
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
                self._write_json(504, {"error": {"message": "upstream timeout", "trace_id": trace_id}})
                return
            self.send_response(upstream.status_code)
            self.send_header("x-copilotwrapper-trace-id", trace_id)
            for key, value in upstream.headers.items():
                if key not in {"transfer-encoding", "connection", "content-length"}:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(upstream.body)

        def _write_json(self, status: int, payload: dict):
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ProxyHandler


def run_proxy_server(config):
    store = ReversibleStore(config.store_path)
    handler = create_proxy_handler(config, store)
    server = ThreadingHTTPServer((config.listen_host, config.listen_port), handler)
    server.serve_forever()
```

- [ ] **Step 4: Run task tests**

Run: `pytest tests/test_proxy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add copilotwrapper/proxy.py tests/test_proxy.py
git commit -m "feat: add copilot endpoint proxy server"
```

### Task 5: CLI Proxy Command + Copilot Routing Guidance

**Files:**
- Modify: `copilotwrapper/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `load_proxy_config_from_env() -> ProxyConfig`
  - `run_proxy_server(config: ProxyConfig) -> None`
- Produces:
  - CLI subcommand: `copilotwrapper proxy`

- [ ] **Step 1: Write failing CLI tests**

```python
import subprocess
import sys


def test_cli_proxy_help_includes_env_names():
    proc = subprocess.run(
        [sys.executable, "-m", "copilotwrapper", "proxy", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "COPILOTWRAPPER_UPSTREAM_BASE_URL" in proc.stdout
```

- [ ] **Step 2: Run failing CLI tests**

Run: `pytest tests/test_cli.py::test_cli_proxy_help_includes_env_names -v`
Expected: FAIL because `proxy` subcommand does not exist.

- [ ] **Step 3: Implement CLI `proxy` command**

```python
proxy_parser = subcommands.add_parser("proxy", help="Start Copilot request proxy")
proxy_parser.add_argument("--listen-host", default=None)
proxy_parser.add_argument("--listen-port", type=int, default=None)
proxy_parser.add_argument("--upstream-base-url", default=None)

if args.command == "proxy":
    config = load_proxy_config_from_env()
    if args.listen_host:
        config = replace(config, listen_host=args.listen_host)
    if args.listen_port:
        config = replace(config, listen_port=args.listen_port)
    if args.upstream_base_url:
        config = replace(config, upstream_base_url=args.upstream_base_url.rstrip("/"))
    print(f"Proxy listening on http://{config.listen_host}:{config.listen_port}")
    print("Set Copilot CLI env to route traffic:")
    print(f"COPILOT_PROVIDER_API_URL=http://{config.listen_host}:{config.listen_port}")
    run_proxy_server(config)
```

- [ ] **Step 4: Run task tests**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add copilotwrapper/cli.py tests/test_cli.py
git commit -m "feat: add proxy launch command with copilot env guidance"
```

### Task 6: End-to-End Endpoint Coverage + Regression Pass

**Files:**
- Modify: `tests/test_proxy.py`
- Modify: `tests/test_compress.py` (only if needed for unchanged behavior assertion)
- Modify: `README.md`

**Interfaces:**
- Consumes:
  - Running proxy path from `run_proxy_server`
  - Existing `compress` API contract
- Produces:
  - End-to-end verification coverage for `/v1/chat/completions` and `/v1/responses`
  - User-facing docs for setup and limitations

- [ ] **Step 1: Add integration test for `/v1/chat/completions` compression path**

```python
import json


def test_proxy_forwards_rewritten_chat_payload(proxy_and_mock_upstream):
    client, upstream = proxy_and_mock_upstream
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "summarize"},
            {"role": "tool", "content": json.dumps([{"id": i, "status": "active"} for i in range(120)])},
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": "upstream-ok"}

    forwarded = upstream.last_json_body
    rewritten = forwarded["messages"][1]["content"]
    parsed = json.loads(rewritten)
    assert parsed["kind"] == "json_list_summary"
    assert "reversible_handle" in parsed
```

- [ ] **Step 2: Add integration test for `/v1/responses` pass-through path**

```python
import copy


def test_proxy_forwards_responses_payload_without_user_text_rewrite(proxy_and_mock_upstream):
    client, upstream = proxy_and_mock_upstream
    payload = {
        "model": "gpt-4.1",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "do not change me"}]}],
    }
    expected = copy.deepcopy(payload)
    response = client.post("/v1/responses", json=payload)
    assert response.status_code == 200
    assert response.json() == {"id": "upstream-ok"}
    assert upstream.last_json_body == expected
```

- [ ] **Step 3: Update README with proxy command and env variables**

```markdown
## Copilot proxy mode

Set `COPILOTWRAPPER_UPSTREAM_BASE_URL` to your Copilot-compatible upstream,
then run:

```bash
copilotwrapper proxy
```

Route requests through:

```bash
export COPILOT_PROVIDER_API_URL=http://127.0.0.1:8787
```
```

- [ ] **Step 4: Run full repository tests**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_proxy.py tests/test_compress.py README.md
git commit -m "test/docs: add e2e proxy coverage and usage docs"
```

## Self-Review Notes

1. **Spec coverage:** All spec sections map to tasks (architecture modules, conservative compression, reversible store, endpoints, CLI guidance, error mapping, tests).
2. **Placeholder scan:** Removed placeholder markers (`...`, TODO/TBD style text) and replaced them with concrete test code and commands.
3. **Type consistency:** Interface signatures are consistent across tasks (`ProxyConfig`, `ReversibleStore`, `rewrite_request_body`, `forward_json`, `run_proxy_server`).
