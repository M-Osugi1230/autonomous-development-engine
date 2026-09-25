from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import ProjectState


class StateStore:
    """Load and atomically persist ADE project state."""

    def __init__(self, path: str | Path = ".autodev/state.json") -> None:
        self.path = Path(path)

    def load(self) -> ProjectState:
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("state file must contain a JSON object")
        return ProjectState.from_dict(payload)

    def save(self, state: ProjectState) -> None:
        payload = state.to_dict()
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
