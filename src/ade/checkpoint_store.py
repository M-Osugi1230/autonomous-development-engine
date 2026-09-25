from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .checkpoint import TaskCheckpoint


class CheckpointStore:
    """Load and atomically persist ADE task checkpoints."""

    def __init__(self, path: str | Path = ".autodev/runtime/checkpoint.json") -> None:
        self.path = Path(path)

    def load(self) -> TaskCheckpoint:
        if not self.path.exists():
            raise FileNotFoundError(f"checkpoint file not found: {self.path}")

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as err:
            raise ValueError(f"checkpoint file contains invalid JSON: {err}") from err

        if not isinstance(payload, dict):
            raise ValueError("checkpoint file must contain a JSON object")

        try:
            return TaskCheckpoint.from_dict(payload)
        except (ValueError, TypeError, KeyError) as err:
            raise ValueError(f"invalid task checkpoint payload: {err}") from err

    def save(self, checkpoint: TaskCheckpoint) -> None:
        if not isinstance(checkpoint, TaskCheckpoint):
            raise TypeError(f"expected TaskCheckpoint, got {type(checkpoint).__name__}")

        payload = checkpoint.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
