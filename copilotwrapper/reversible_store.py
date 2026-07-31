from __future__ import annotations

import json
from pathlib import Path
from time import time


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
            for line in file_handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("handle") == handle:
                    return row
        return None
