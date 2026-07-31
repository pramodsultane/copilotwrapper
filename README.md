# copilotwrapper

copilotwrapper is a clean-room, open-source wrapper framework for AI coding assistant workflows.

## Clean-Room First

This repository is intentionally built from scratch as an original implementation.

- No copied code from existing projects.
- No mirrored internal logic patterns.
- No verbatim structural reuse from protected works.

See the full architecture and compliance specification:
- docs/CLEAN_ROOM_SPEC.md

## Copilot proxy mode

Set `COPILOTWRAPPER_UPSTREAM_BASE_URL` to your Copilot-compatible upstream, then run:

```bash
copilotwrapper proxy
```

Alternatively, pass the upstream directly on the command line without setting the
environment variable:

```bash
copilotwrapper proxy --upstream-base-url https://api.githubcopilot.com
```

The upstream URL (from either source) must start with `http://` or `https://`; it is
validated at startup so a misconfigured scheme fails fast with a clear CLI error
instead of crashing later on the first request.

Route requests through:

```bash
export COPILOT_PROVIDER_API_URL=http://127.0.0.1:8787
```

Other supported environment variables: `COPILOTWRAPPER_LISTEN_HOST`,
`COPILOTWRAPPER_LISTEN_PORT`, `COPILOTWRAPPER_MIN_TOKENS`, `COPILOTWRAPPER_STORE_PATH`,
`COPILOTWRAPPER_TIMEOUT_SECONDS`, and `COPILOTWRAPPER_MAX_BODY_BYTES` (request body size
cap in bytes, default 10 MiB; oversized requests receive a structured `413` error).

## Limitations

- **Chunked request bodies are not supported.** The proxy only accepts requests with an
  explicit `Content-Length` header. Requests sent with `Transfer-Encoding: chunked` are
  rejected with a structured `501` error; requests missing `Content-Length` entirely are
  rejected with a structured `411` error. Configure your HTTP client to send a
  non-chunked body with `Content-Length`.
- **Request body size is capped** at `COPILOTWRAPPER_MAX_BODY_BYTES` (default 10 MiB).
  Requests declaring a larger `Content-Length` are rejected with a structured `413`
  error before the body is read into memory.
- **Streaming responses are currently buffered end-to-end.** The proxy waits for the
  full upstream response body before returning it to the client. For `stream: true`
  workloads (for example, SSE-style incremental tokens), this means responses are
  delivered only after upstream completion instead of incrementally.
- **The reversible store is a plaintext, append-only, unbounded log.** By default it is
  written to `.copilotwrapper-store.jsonl` in the working directory. It contains the
  original (pre-compression) content of rewritten tool/message segments so that
  responses can reference it later via a `reversible_handle`. It is never automatically
  rotated, expired, or encrypted, and it can grow without bound over the life of a
  running proxy. Treat this file as sensitive: restrict its filesystem permissions, keep
  it out of version control (the default filename is covered by `.gitignore`), and
  periodically rotate or delete it in line with your own data-retention requirements.
- The `/v1/responses` endpoint is currently passthrough-only (no compression/rewrite is
  applied yet).

## License

This project is licensed under MIT.

## Planned Layout

```text
copilotwrapper/
  docs/
    CLEAN_ROOM_SPEC.md
  src/
  tests/
  tools/
  .github/
```
