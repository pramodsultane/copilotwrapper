from __future__ import annotations

import json
import subprocess
import sys


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