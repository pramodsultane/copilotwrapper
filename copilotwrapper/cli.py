from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .compress import compress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="copilotwrapper")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("compress", help="Compress JSON messages from stdin")

    args = parser.parse_args(argv)

    if args.command == "compress":
        payload = json.load(sys.stdin)
        result = compress(payload)
        json.dump(asdict(result), sys.stdout)
        sys.stdout.write("\n")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2