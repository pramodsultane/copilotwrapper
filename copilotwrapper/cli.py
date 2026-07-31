from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace

from .compress import compress
from .config import load_proxy_config_from_env
from .proxy import run_proxy_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="copilotwrapper")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("compress", help="Compress JSON messages from stdin")
    proxy_parser = subcommands.add_parser(
        "proxy",
        help="Start Copilot request proxy",
        description=(
            "Start the local Copilot proxy server.\n\n"
            "Environment:\n"
            "  COPILOTWRAPPER_UPSTREAM_BASE_URL (required)\n"
            "  COPILOTWRAPPER_LISTEN_HOST (default: 127.0.0.1)\n"
            "  COPILOTWRAPPER_LISTEN_PORT (default: 8787)\n"
            "  COPILOTWRAPPER_MIN_TOKENS (default: 250)\n"
            "  COPILOTWRAPPER_STORE_PATH (default: .copilotwrapper-store.jsonl)\n"
            "  COPILOTWRAPPER_TIMEOUT_SECONDS (default: 30)\n"
            "  COPILOTWRAPPER_MAX_BODY_BYTES (default: 10485760)"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    proxy_parser.add_argument("--listen-host", default=None)
    proxy_parser.add_argument("--listen-port", type=int, default=None)
    proxy_parser.add_argument("--upstream-base-url", default=None)

    args = parser.parse_args(argv)

    if args.command == "compress":
        payload = json.load(sys.stdin)
        result = compress(payload)
        json.dump(asdict(result), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "proxy":
        try:
            # Pass the CLI flag in *before* the required-env check so
            # `--upstream-base-url` alone is sufficient to start the proxy
            # without COPILOTWRAPPER_UPSTREAM_BASE_URL being set.
            config = load_proxy_config_from_env(upstream_base_url_override=args.upstream_base_url)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        if args.listen_host:
            config = replace(config, listen_host=args.listen_host)
        if args.listen_port is not None:
            config = replace(config, listen_port=args.listen_port)
        print(f"Proxy listening on http://{config.listen_host}:{config.listen_port}")
        print("Set Copilot CLI env to route traffic:")
        print(f"COPILOT_PROVIDER_API_URL=http://{config.listen_host}:{config.listen_port}")
        run_proxy_server(config)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2