Status: DONE

## Summary of files changed
- Added `copilotwrapper/forwarder.py` with:
  - `UpstreamResponse` dataclass (`status_code`, `headers`, `body`)
  - `forward_json(...)` POST helper for JSON forwarding
  - upstream URL scheme validation (`http`/`https` only)
  - hop-by-hop header filtering (`connection`, `host`, `content-length`, etc.)
  - timeout passthrough into upstream call
  - response status/header/body passthrough
- Added `tests/test_forwarder.py` with coverage for:
  - non-HTTP upstream rejection (`ValueError`)
  - forwarding behavior, header filtering, and response passthrough

## Exact commands run and test output summary
1. `cd /home/e056197/github/copilotwrapper && pytest tests/test_forwarder.py -v`
   - Result: **FAIL** during collection (`ModuleNotFoundError: No module named 'copilotwrapper'`) in this environment.
2. `cd /home/e056197/github/copilotwrapper && pytest tests/test_forwarder.py -v`
   - Result: **FAIL** during collection (expected red phase before implementation; same environment import issue).
3. `cd /home/e056197/github/copilotwrapper && pytest tests/test_forwarder.py -v ; python -m pytest tests/test_forwarder.py -v`
   - Result:
     - `pytest ...`: **FAIL** (same environment-specific import issue)
     - `python -m pytest ...`: **PASS** — 2 passed in 0.03s

## Commit SHA(s)
- `b80b449`

## Concerns
- In this environment, direct `pytest` entrypoint does not resolve local package imports, while `python -m pytest` works and passes task tests.

---

## Task 3 review fixes (2026-07-31)

### Findings addressed
1. **High security:** prevented absolute endpoint override by enforcing `endpoint` to be path-only (rejects scheme/netloc/query/fragment/params).
2. **High reliability:** converted upstream `HTTPError` into `UpstreamResponse` so non-2xx responses are passed through with status/headers/body.

### Additional tests added
- `test_forward_json_rejects_absolute_endpoint`
- `test_forward_json_passes_through_http_error_response`

### Verification commands and results
1. `python -m pytest tests/test_forwarder.py -q` → **4 passed**
2. `python -m pytest tests -q` → **23 passed**

## Task 3 remaining finding fix (2026-07-31)

### Finding addressed
- **Medium:** Prevented incoming `Content-Type` from overriding JSON forwarding content type in `forward_json`, avoiding header/body mismatch.

### Changes
- Updated `copilotwrapper/forwarder.py` to ignore any incoming header whose case-insensitive name is `content-type` while still forwarding other allowed headers.
- Added `test_forward_json_does_not_allow_incoming_content_type_override` in `tests/test_forwarder.py`.

### Verification
1. `python -m pytest tests/test_forwarder.py -q` → **5 passed**
2. `python -m pytest tests -q` → **24 passed**
