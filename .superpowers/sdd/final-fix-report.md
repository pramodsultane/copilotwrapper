# Final Fix Report — Consolidated Review Findings Pass

Date: 2026-07-31

## Scope

Single consolidated fix pass addressing all blocking findings from the final
review round (2 critical, 4 important). Clean-room, `copilotwrapper` only.

## Findings and Fixes

### 1) Critical — Proxy crashes on forwarder `ValueError` (misconfigured upstream scheme)

- **Root cause:** `forwarder.forward_json` raises `ValueError` for a non
  `http(s)` upstream scheme or a non path-only endpoint. `proxy.py`'s
  `do_POST` only caught `TimeoutError`, `URLError`, and `OSError` around the
  `forward_json` call, so a `ValueError` propagated out of the request
  handler thread as an unhandled exception (crashing that request, logged as
  a broken-pipe/500 by `http.server`, no structured client response).
- **Fix:**
  - `config.py`: added `_normalize_upstream_base_url`, called from
    `load_proxy_config_from_env`, which validates the upstream scheme is
    `http`/`https` at config-load time (CLI startup or programmatic use),
    turning a misconfigured upstream into an immediate, clear startup error
    instead of a later request-time crash.
  - `proxy.py`: added a defense-in-depth `except ValueError` around the
    `forward_json` call that returns a structured `502` JSON error
    (`{"error": {"message": "invalid upstream configuration", "trace_id": ...}}`)
    instead of letting the exception escape.
- **Tests added:**
  - `tests/test_config.py::test_load_proxy_config_rejects_invalid_upstream_scheme`
    (parametrized: `ftp://`, no scheme, empty, whitespace-only).
  - `tests/test_cli.py::test_cli_proxy_rejects_invalid_upstream_scheme_from_flag`
  - `tests/test_proxy.py::test_proxy_returns_502_when_forwarder_raises_valueerror_for_misconfigured_upstream`

### 2) Critical — Chunked request bodies rejected as misleading "invalid json" (400)

- **Root cause:** `_read_request_bytes` only looked at `Content-Length`
  (defaulting to `"0"` when absent). A chunked request (`Transfer-Encoding:
  chunked`, no `Content-Length`) read zero bytes, then `json.loads(b"")`
  raised `JSONDecodeError`, surfaced to the client as a generic `400 invalid
  json` — misleading, since the actual problem is unsupported transfer
  encoding, not malformed JSON.
- **Fix:** `proxy.py::_read_request_bytes` now:
  - Detects `Transfer-Encoding: chunked` (case-insensitive, handles
    comma-separated coding lists) and raises a new `_RequestBodyError(501,
    "chunked request bodies are not supported")`.
  - Treats a fully missing `Content-Length` header (no chunked encoding
    either) as `_RequestBodyError(411, "content-length header is required")`
    rather than silently defaulting to `0`.
  - `do_POST` catches `_RequestBodyError` and returns the carried status code
    with a structured JSON error body, before ever attempting JSON parsing.
- **Tests added:**
  - `tests/test_proxy.py::test_proxy_returns_501_for_chunked_request_body`
  - `tests/test_proxy.py::test_proxy_returns_411_when_content_length_missing`
  - Added a raw-socket-capable `_raw_request` helper / `raw_post` method to
    the test HTTP client since `urllib.request` cannot omit `Content-Length`
    or hand-construct chunked framing.

### 3) Important — `--upstream-base-url` flag unusable (env checked before flag override)

- **Root cause:** `cli.py` called `load_proxy_config_from_env()` (which
  raises if `COPILOTWRAPPER_UPSTREAM_BASE_URL` is unset) *before* applying
  `args.upstream_base_url`, so the flag could never be used standalone to
  start the proxy — the env var was always required regardless of the flag.
- **Fix:**
  - `config.py`: `load_proxy_config_from_env` now accepts
    `upstream_base_url_override: str | None = None`; when provided it takes
    precedence over the environment variable and satisfies the "required"
    check by itself.
  - `cli.py`: passes `args.upstream_base_url` into
    `load_proxy_config_from_env(upstream_base_url_override=...)` up front,
    removing the old post-hoc `replace(...)` override (now redundant/dead).
- **Tests added/updated:**
  - `tests/test_config.py::test_load_proxy_config_upstream_override_takes_precedence_over_env`
  - `tests/test_config.py::test_load_proxy_config_upstream_override_works_without_env_var`
  - `tests/test_cli.py::test_cli_proxy_upstream_base_url_flag_works_without_env_var`
  - Updated `tests/test_cli.py::test_cli_proxy_listen_port_zero_override_is_applied`
    monkeypatch lambda to accept the new keyword argument.

### 4) Important — No request body size limit (unbounded memory read)

- **Root cause:** `_read_request_bytes` called `self.rfile.read(length)` for
  any declared `Content-Length`, with no upper bound, allowing a caller to
  force large memory allocations.
- **Fix:**
  - `config.py`: added `ProxyConfig.max_request_body_bytes` (default
    10 MiB = `10 * 1024 * 1024`), configurable via
    `COPILOTWRAPPER_MAX_BODY_BYTES`.
  - `proxy.py::_read_request_bytes`: checks the declared `Content-Length`
    against `config.max_request_body_bytes` *before* calling `rfile.read`,
    raising `_RequestBodyError(413, "request body exceeds maximum allowed
    size of N bytes")` when exceeded.
  - CLI `--help` text and README updated to document the new env var and
    behavior.
- **Tests added:**
  - `tests/test_config.py::test_load_proxy_config_reads_custom_values` (now
    covers `COPILOTWRAPPER_MAX_BODY_BYTES`), plus defaults assertion in
    `test_load_proxy_config_defaults`.
  - `tests/test_proxy.py::test_proxy_returns_413_when_body_exceeds_max_size`
    (spins up a proxy with a small `max_request_body_bytes` and asserts the
    structured `413`).

### 5) Important — Reversible promise not exercised end-to-end

- **Root cause:** Existing e2e test
  (`test_proxy_forwards_rewritten_chat_payload`) asserted a
  `reversible_handle` was present in the rewritten payload sent upstream,
  but never verified the handle actually resolves back to the original
  content via `ReversibleStore.get` — the core reversibility guarantee was
  unverified end-to-end.
- **Fix:** Extended the `proxy_and_mock_upstream` fixture to also yield the
  `ReversibleStore` instance backing the running proxy. Updated
  `test_proxy_forwards_rewritten_chat_payload` to capture the original
  (pre-compression) tool message content, extract the emitted
  `reversible_handle` from the forwarded/rewritten payload, call
  `store.get(handle)`, and assert the stored `payload` equals the original
  content byte-for-byte — a genuine round-trip assertion through the real
  HTTP proxy, pipeline, and store.
- **Tests changed:** `tests/test_proxy.py::test_proxy_forwards_rewritten_chat_payload`
  (extended); `test_proxy_forwards_responses_payload_without_user_text_rewrite`
  updated for the fixture's new 3-tuple shape.

### 6) Important — Default reversible store commit hazard / plaintext risk

- **Root cause:** The default store path (`.copilotwrapper-store.jsonl`,
  written to the current working directory) was not covered by any
  `.gitignore`, and its plaintext, unbounded, unencrypted nature was
  undocumented — a real risk of accidentally committing sensitive original
  request content.
- **Fix:**
  - Added root-level `.gitignore` with an entry for the default store
    filename/pattern (`.copilotwrapper-store.jsonl`, `*.copilotwrapper-store.jsonl`).
  - Added a "Limitations" section to `README.md` explicitly documenting:
    plaintext/append-only/unbounded nature of the store, no automatic
    rotation/expiry/encryption, recommendation to restrict file permissions
    and rotate/delete per the operator's own retention policy, and that the
    default filename is excluded from version control.
- No code test applicable (documentation/repo-hygiene fix); verified by
  inspecting `git status` after the full test run confirms no store file is
  tracked or untracked at the repo root.

## Other Documentation Updates

- README: proxy section now documents `--upstream-base-url` as a
  standalone alternative to the env var, notes the early scheme validation,
  lists all supported environment variables, and adds the new
  "Limitations" section (chunked bodies, body size cap, store retention
  risk, `/v1/responses` passthrough-only note carried over from prior
  state).
- CLI `--help` (`proxy_parser` description) now lists
  `COPILOTWRAPPER_MAX_BODY_BYTES` alongside existing env vars.

## Tests Run

```
PYTHONPATH=. python -m pytest -v
```

Result: **46 passed**, 0 failed (34 pre-existing + 12 new/adjusted for this
pass: 6 in `test_config.py`, 3 in `test_cli.py`, and additions/updates in
`test_proxy.py` covering 501/411/413/502(ValueError)/round-trip).

No linter/build config beyond `pytest` exists in `pyproject.toml`; no
additional tooling was introduced per task constraints.

## Unresolved / Out of Scope

None of the six blocking findings are unresolved. Minor/non-blocking items
noted during review (e.g. `/v1/responses` compression being passthrough-only,
pre-existing tracked `__pycache__` files in git) were intentionally left
untouched to avoid scope creep, per task instructions.
