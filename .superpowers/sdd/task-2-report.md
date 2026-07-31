Status: DONE

## Summary of files changed
- Added `copilotwrapper/pipeline.py` implementing conservative endpoint rewrite pipeline with:
  - `RewriteResult`
  - `rewrite_request_body(...)`
  - chat rewrite path that applies `compress(...)` and attaches reversible handles for transformed string content
  - responses rewrite path passthrough (conservative, no rewriting)
- Added `tests/test_pipeline.py` with coverage for:
  - `/v1/chat/completions` large tool JSON rewrite + reversible handle injection
  - `/v1/responses` plain user text passthrough/no transforms

## Exact test commands run and output summary
1. `cd /home/e056197/github/copilotwrapper && pytest tests/test_pipeline.py -v`
   - Result: **FAIL** (expected RED phase) — import/module collection error.
2. `cd /home/e056197/github/copilotwrapper && pytest tests/test_pipeline.py tests/test_compress.py -v`
   - Result: **FAIL** — same environment-specific import/module collection error.
3. `cd /home/e056197/github/copilotwrapper && python -m pytest tests/test_pipeline.py tests/test_compress.py -v`
   - Result: **PASS** — 4 passed in 0.05s.

## Commit SHA(s)
- `1337b0f`

## Concerns
- In this environment, `pytest ...` (entrypoint script) did not resolve local package import, while `python -m pytest ...` worked and passed; task-specific verification used the working invocation.

---

## Follow-up fixes for review findings (2026-07-31)

### Findings addressed
1. **High: non-tool user content rewrite risk**
   - Updated `copilotwrapper/pipeline.py` chat rewrite path to compress only **tool/tool-result style** messages (`role == "tool"` or `tool_call_id` present).
   - Non-tool user/assistant messages are never passed to compression and remain unchanged.

2. **Medium: malformed message entries could crash**
   - Added shape validation for `messages` entries; non-dict entries now fail-open to passthrough with explicit fallback log.
   - Added guarded failure paths around compress and handle-attachment stages with fail-open behavior and explicit reason logging.

3. **Medium: silent fallback paths**
   - Added structured fallback logging in all passthrough/failure branches:
     - `unsupported_endpoint_passthrough`
     - `chat_messages_not_list`
     - `chat_messages_non_object_entry`
     - `chat_no_tool_style_messages`
     - `chat_compress_failure`
     - `chat_attach_handle_failure`
     - `responses_passthrough_conservative`

### Tests updated
- `tests/test_pipeline.py`
  - Added regression test ensuring large JSON in **user** chat content is not rewritten.
  - Added malformed entry fail-open + structured reason log assertion.
  - Added attach-handle failure fail-open + structured reason log assertion.
  - Added responses passthrough reason log assertion.
  - Added unsupported endpoint passthrough reason log assertion.

### Verification evidence
- Command:
  - `python -m pytest tests/test_pipeline.py tests/test_compress.py -q`
- Result:
  - `9 passed in 0.05s`

---

## Remaining Task 2 high-severity fix (2026-07-31)

### Finding addressed
- **High:** unhandled `store.put(...)` exceptions could crash `/v1/chat/completions` rewrite path during reversible handle attachment.

### Root cause
- `_attach_handles(...)` called `store.put(...)` without guarding non-validation exceptions (for example `OSError` from storage I/O), and `_rewrite_chat(...)` only fail-open handled attach-stage parse/validation exception types.

### Code change
- Added `_StoreWriteError` in `copilotwrapper/pipeline.py` to carry failing message index and original exception.
- Wrapped `store.put(...)` in `_attach_handles(...)`; on failure it raises `_StoreWriteError`.
- Added `_rewrite_chat(...)` handling for `_StoreWriteError` that:
  - logs structured fallback reason `chat_store_write_failure` with `error_type`, `error`, and `index`
  - returns fail-open passthrough (`body` unchanged, `transforms_applied=[]`).

### Tests added/updated
- `tests/test_pipeline.py`
  - Added `test_chat_rewrite_store_put_failure_falls_back_with_reason_log`:
    - monkeypatches `store.put` to raise `OSError("disk full")`
    - verifies `rewrite_request_body(...)` returns original body
    - verifies no transforms are applied
    - asserts structured fallback log reason `chat_store_write_failure`.

### Verification evidence
- Command:
  - `python -m pytest tests/test_pipeline.py tests/test_compress.py tests/test_reversible_store.py -q`
- Result:
  - `15 passed in 0.07s`
