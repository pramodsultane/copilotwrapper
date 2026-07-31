from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from copilotwrapper.cli import main
from copilotwrapper.config import ProxyConfig


def test_module_cli_compresses_json_messages() -> None:
    messages = [
        {"role": "user", "content": "summarize"},
        {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": json.dumps([
                {"id": index, "status": "active"}
                for index in range(120)
            ]),
        },
    ]

    proc = subprocess.run(
        [sys.executable, "-m", "copilotwrapper", "compress"],
        input=json.dumps(messages),
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["tokens_saved"] > 0
    assert result["messages"] != messages


def test_cli_proxy_help_includes_env_names() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "copilotwrapper", "proxy", "--help"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "COPILOTWRAPPER_UPSTREAM_BASE_URL" in proc.stdout


def test_cli_proxy_missing_required_env_exits_with_user_facing_error() -> None:
    env = os.environ.copy()
    env.pop("COPILOTWRAPPER_UPSTREAM_BASE_URL", None)

    proc = subprocess.run(
        [sys.executable, "-m", "copilotwrapper", "proxy"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    assert "COPILOTWRAPPER_UPSTREAM_BASE_URL is required" in proc.stderr
    assert "Error:" in proc.stderr


def test_cli_proxy_listen_port_zero_override_is_applied(monkeypatch) -> None:
    base_config = ProxyConfig(
        listen_host="127.0.0.1",
        listen_port=8787,
        upstream_base_url="https://example.test",
        min_tokens_to_compress=250,
        store_path=".copilotwrapper-store.jsonl",
        request_timeout_seconds=30.0,
    )
    monkeypatch.setattr(
        "copilotwrapper.cli.load_proxy_config_from_env",
        lambda **kwargs: base_config,
    )
    captured: dict[str, ProxyConfig] = {}

    def fake_run_proxy_server(config: ProxyConfig) -> None:
        captured["config"] = config

    monkeypatch.setattr("copilotwrapper.cli.run_proxy_server", fake_run_proxy_server)

    exit_code = main(["proxy", "--listen-port", "0"])

    assert exit_code == 0
    assert captured["config"].listen_port == 0


def test_cli_proxy_upstream_base_url_flag_works_without_env_var(monkeypatch) -> None:
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)
    captured: dict[str, ProxyConfig] = {}

    def fake_run_proxy_server(config: ProxyConfig) -> None:
        captured["config"] = config

    monkeypatch.setattr("copilotwrapper.cli.run_proxy_server", fake_run_proxy_server)

    exit_code = main(["proxy", "--upstream-base-url", "https://example.test/base/", "--listen-port", "0"])

    assert exit_code == 0
    assert captured["config"].upstream_base_url == "https://example.test/base"


def test_cli_proxy_rejects_invalid_upstream_scheme_from_flag(monkeypatch) -> None:
    monkeypatch.delenv("COPILOTWRAPPER_UPSTREAM_BASE_URL", raising=False)

    proc = subprocess.run(
        [sys.executable, "-m", "copilotwrapper", "proxy", "--upstream-base-url", "ftp://example.test"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode != 0
    assert "http://" in proc.stderr or "https://" in proc.stderr
    assert "Error:" in proc.stderr