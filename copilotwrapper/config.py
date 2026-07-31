from __future__ import annotations

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
    upstream_base_url = os.getenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "").strip()
    if not upstream_base_url:
        raise ValueError("COPILOTWRAPPER_UPSTREAM_BASE_URL is required")

    return ProxyConfig(
        listen_host=os.getenv("COPILOTWRAPPER_LISTEN_HOST", "127.0.0.1"),
        listen_port=int(os.getenv("COPILOTWRAPPER_LISTEN_PORT", "8787")),
        upstream_base_url=upstream_base_url.rstrip("/"),
        min_tokens_to_compress=int(os.getenv("COPILOTWRAPPER_MIN_TOKENS", "250")),
        store_path=os.getenv("COPILOTWRAPPER_STORE_PATH", ".copilotwrapper-store.jsonl"),
        request_timeout_seconds=float(os.getenv("COPILOTWRAPPER_TIMEOUT_SECONDS", "30")),
    )
