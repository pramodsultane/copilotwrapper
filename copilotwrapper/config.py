from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse

_VALID_UPSTREAM_SCHEMES = {"http", "https"}
_DEFAULT_MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB


@dataclass(frozen=True)
class ProxyConfig:
    listen_host: str
    listen_port: int
    upstream_base_url: str
    min_tokens_to_compress: int
    store_path: str
    request_timeout_seconds: float
    max_request_body_bytes: int = _DEFAULT_MAX_REQUEST_BODY_BYTES


def _normalize_upstream_base_url(raw: str) -> str:
    """Strip, trim trailing slash, and validate the upstream scheme early.

    Raising here (at config load time, before the server starts) turns a
    misconfigured upstream into a fail-fast startup error instead of a
    request-time crash inside the forwarder.
    """
    value = raw.strip().rstrip("/")
    scheme = urlparse(value).scheme
    if scheme not in _VALID_UPSTREAM_SCHEMES:
        raise ValueError(
            "upstream base URL must start with http:// or https:// "
            f"(got: {value!r})"
        )
    return value


def load_proxy_config_from_env(*, upstream_base_url_override: str | None = None) -> ProxyConfig:
    """Load proxy configuration from environment variables.

    ``upstream_base_url_override`` (typically sourced from the ``--upstream-base-url``
    CLI flag) takes precedence over ``COPILOTWRAPPER_UPSTREAM_BASE_URL`` and allows the
    proxy to start without the environment variable being set at all.
    """
    upstream_base_url = (upstream_base_url_override or os.getenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "")).strip()
    if not upstream_base_url:
        raise ValueError(
            "COPILOTWRAPPER_UPSTREAM_BASE_URL is required (or pass --upstream-base-url)"
        )
    upstream_base_url = _normalize_upstream_base_url(upstream_base_url)

    return ProxyConfig(
        listen_host=os.getenv("COPILOTWRAPPER_LISTEN_HOST", "127.0.0.1"),
        listen_port=int(os.getenv("COPILOTWRAPPER_LISTEN_PORT", "8787")),
        upstream_base_url=upstream_base_url,
        min_tokens_to_compress=int(os.getenv("COPILOTWRAPPER_MIN_TOKENS", "250")),
        store_path=os.getenv("COPILOTWRAPPER_STORE_PATH", ".copilotwrapper-store.jsonl"),
        request_timeout_seconds=float(os.getenv("COPILOTWRAPPER_TIMEOUT_SECONDS", "30")),
        max_request_body_bytes=int(
            os.getenv("COPILOTWRAPPER_MAX_BODY_BYTES", str(_DEFAULT_MAX_REQUEST_BODY_BYTES))
        ),
    )
