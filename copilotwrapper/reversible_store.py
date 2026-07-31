from __future__ import annotations

import json
import logging
from pathlib import Path
from time import time

_LOGGER = logging.getLogger(__name__)


class ReversibleStore:
    def __init__(self, file_path: str | Path):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def put(self, handle: str, payload: object, trace_id: str, segment_path: str) -> None:
        row = {
            "handle": handle,
            "trace_id": trace_id,
            "segment_path": segment_path,
            "payload": payload,
            "created_at": time(),
        }
        with self._path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(json.dumps(row, separators=(",", ":")))
            file_handle.write("\n")

    def get(self, handle: str) -> dict[str, object] | None:
        with self._path.open("r", encoding="utf-8") as file_handle:
            for line_number, line in enumerate(file_handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    _LOGGER.warning(
                        "reversible_store_malformed_jsonl_line path=%s line_number=%d error=%s",
                        str(self._path),
                        line_number,
                        str(exc),
                    )
                    continue
                if not isinstance(row, dict):
                    _LOGGER.warning(
                        "reversible_store_non_object_jsonl_row path=%s line_number=%d row_type=%s",
                        str(self._path),
                        line_number,
                        type(row).__name__,
                    )
                    continue
                if row.get("handle") == handle:
                    return row
        return None
