# Copilotwrapper v1 Copilot Token-Saving Proxy Design

Date: 2026-07-31
Status: Approved for planning

## 1. Objective

Implement a clean-room, Copilot-focused token-saving proxy inside `copilotwrapper` that reduces request size before payloads reach the upstream LLM service used by GitHub Copilot CLI.

## 2. Scope

### In scope

- Local HTTP reverse proxy for:
  - `POST /v1/chat/completions`
  - `POST /v1/responses`
- Conservative request compression:
  - Only large JSON/tool-style payload segments
  - Do not rewrite normal user prose by default
- Reversible rewrite support:
  - Store original segments locally
  - Replace rewritten sections with handles and summary metadata
- CLI command for launching proxy and showing environment guidance for Copilot CLI routing
- Unit/integration tests for rewrite logic and proxy passthrough behavior

### Out of scope (v1)

- Non-Copilot protocol support beyond OpenAI-compatible endpoints listed above
- Advanced semantic/text compression of normal user instructions
- Distributed/shared reversible cache

## 3. Architecture

The implementation will add focused modules under `copilotwrapper/`:

- `config.py`: environment and runtime configuration parsing
- `proxy.py`: HTTP server and route dispatch for supported endpoints
- `forwarder.py`: upstream request forwarding and response passthrough
- `pipeline.py`: conservative content-aware rewrite pipeline orchestration
- `reversible_store.py`: local handle-based cache of original payload fragments

The current `compress.py` remains available and unchanged for existing CLI compression workflows.

## 4. Request Lifecycle

1. Receive request on supported endpoint.
2. Parse JSON body and attach a trace identifier.
3. Evaluate payload segments for conservative compression eligibility.
4. For eligible segments:
   - Save original segment in local reversible store with deterministic handle.
   - Replace segment content with compact summary payload including handle.
5. Forward rewritten request to configured upstream Copilot-compatible base URL.
6. Return upstream status/body/headers (with safe header filtering).
7. Emit structured logs for observability and fallback reasons.

## 5. Compression Rules (Conservative Mode)

- Only consider content associated with tool output/tool-result style messages.
- Only compress large JSON structures that cross a size/token threshold.
- Preserve message order and non-target content exactly.
- If no eligible segment exists, forward unchanged.

Summary payload shape (conceptual):

```json
{
  "kind": "json_tool_summary",
  "item_count": 123,
  "keys": ["id", "status", "value"],
  "preview": [{"id": 1, "status": "active"}],
  "reversible_handle": "cw:trace:segment"
}
```

## 6. Reversible Store

- Local file-backed store under configurable path.
- Handle-indexed records containing:
  - Trace ID
  - Segment ID/path
  - Original content blob
  - Timestamp metadata
- Retrieval utility exposed at module level for future CLI/admin use.

Store failure policy:
- If write fails for a segment, do not rewrite that segment; forward original.

## 7. Error Handling and Reliability

- Invalid JSON for supported endpoints: return `400` with explicit error payload.
- Upstream timeout: return `504` with trace ID.
- Transform failure: log and fail open by forwarding original request.
- Reversible-store failure on targeted segment: skip rewrite for that segment and continue safely.
- No silent fallback paths; all fallback reasons logged in structured form.

## 8. CLI Experience

Add command:

```bash
copilotwrapper proxy --listen-host 127.0.0.1 --listen-port 8787 --upstream-base-url <url>
```

On startup, print concise guidance showing how to direct Copilot CLI traffic through the proxy with environment variables or equivalent local configuration.

## 9. Testing Strategy

### Unit tests

- Compression eligibility thresholds and non-eligibility behavior
- Rewrite payload structure and reversible handle generation
- Reversible store write/read behavior
- Config parsing and defaults

### Integration tests

- Mock upstream server receives rewritten payload for eligible segments
- Non-eligible requests pass through unchanged
- `/v1/chat/completions` and `/v1/responses` both work end-to-end
- Upstream error/timeout mapping behavior

### Regression tests

- Existing `copilotwrapper compress` CLI flow remains functional

## 10. Acceptance Criteria

- Local proxy correctly handles both supported endpoints.
- Conservative compression activates only for large JSON/tool payloads.
- Reversible handles are emitted and originals are locally recoverable.
- Proxy forward/pass-through behavior is correct and explicit under error conditions.
- Existing compressor API and tests remain intact.

