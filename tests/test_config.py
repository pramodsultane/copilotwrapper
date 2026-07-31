from __future__ import annotations

from copilotwrapper.config import ProxyConfig, load_proxy_config_from_env


def test_load_proxy_config_defaults(monkeypatch) -> None:
    monkeypatch.setenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", "https://api.githubcopilot.com/")
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_HOST", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_LISTEN_PORT", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_MIN_TOKENS", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_STORE_PATH", raising=False)
    monkeypatch.delenv("COPILOTWRAPPER_TIMEOUT_SECONDS", raising=False)

    cfg = load_proxy_config_from_env()

    assert isinstance(cfg, ProxyConfig)
    assert cfg.listen_host == "127.0.0.1"
    assert cfg.listen_port == 8787
    assert cfg.upstream_base_url == "https://api.githubcopilot.com"
    assert cfg.min_tokens_to_compress == 250
    assert cfg.store_path == ".copilotwrapper-store.jsonl"
    assert cfg.request_timeout_seconds == 30.0


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

    cfg = load_proxy_config_from_env()

    assert cfg == ProxyConfig(
        listen_host="0.0.0.0",
        listen_port=9999,
        upstream_base_url="https://example.test/base",
        min_tokens_to_compress=400,
        store_path="./local-store.jsonl",
        request_timeout_seconds=12.5,
    )
