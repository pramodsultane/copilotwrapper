from __future__ import annotations

import pytest

from copilotwrapper.config import ProxyConfig, load_proxy_config_from_env


def test_load_proxy_config_defaults(monkeypatch) -> None:
    monkeypatch.setenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "https://api.githubcopilot.com/")
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_HOST", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_PORT", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_MIN_TOKENS", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_STORE_PATH", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_MAX_BODY_BYTES", raising=False)

    cfg = load_proxy_config_from_env()

    assert isinstance(cfg, ProxyConfig)
    assert cfg.listen_host == "127.0.0.1"
    assert cfg.listen_port == 8787
    assert cfg.upstream_base_url == "https://api.githubcopilot.com"
    assert cfg.min_tokens_to_compress == 250
    assert cfg.store_path == ".copilotwrapper-store.jsonl"
    assert cfg.request_timeout_seconds == 30.0
    assert cfg.max_request_body_bytes == 10 * 1024 * 1024


def test_load_proxy_config_requires_upstream(monkeypatch) -> None:
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)

    try:
        load_proxy_config_from_env()
    except ValueError as exc:
        assert "COPILOTWRAPPER_UPSTREAM_BASE_URL" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_load_proxy_config_reads_custom_values(monkeypatch) -> None:
    monkeypatch.setenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", " https://example.test/base/ ")
    monkeypatch.setenv("COPILOTWRAPPER_LISTEN_HOST", "0.0.0.0")
    monkeypatch.setenv("COPILOTWRAPPER_LISTEN_PORT", "9999")
    monkeypatch.setenv("COPILOTWRAPPER_MIN_TOKENS", "400")
    monkeypatch.setenv("COPILOTWRAPPER_STORE_PATH", "./local-store.jsonl")
    monkeypatch.setenv("COPILOTWRAPPER_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("COPILOTWRAPPER_MAX_BODY_BYTES", "2048")

    cfg = load_proxy_config_from_env()

    assert cfg == ProxyConfig(
        listen_host="0.0.0.0",
        listen_port=9999,
        upstream_base_url="https://example.test/base",
        min_tokens_to_compress=400,
        store_path="./local-store.jsonl",
        request_timeout_seconds=12.5,
        max_request_body_bytes=2048,
    )


def test_load_proxy_config_upstream_override_takes_precedence_over_env(monkeypatch) -> None:
    monkeypatch.setenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "https://env-value.test")

    cfg = load_proxy_config_from_env(upstream_base_url_override="https://flag-value.test/")

    assert cfg.upstream_base_url == "https://flag-value.test"


def test_load_proxy_config_upstream_override_works_without_env_var(monkeypatch) -> None:
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)

    cfg = load_proxy_config_from_env(upstream_base_url_override="https://flag-only.test")

    assert cfg.upstream_base_url == "https://flag-only.test"


@pytest.mark.parametrize("bad_url", ["ftp://example.test", "example.test", "", "   "])
def test_load_proxy_config_rejects_invalid_upstream_scheme(monkeypatch, bad_url) -> None:
    monkeypatch.setenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", bad_url)

    with pytest.raises(ValueError):
        load_proxy_config_from_env()

