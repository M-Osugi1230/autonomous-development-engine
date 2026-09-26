from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .preview import PreviewManifest


SCHEMA_VERSION = 1
DEFAULT_PREVIEW_PATH = Path(".autodev/preview.json")


class PreviewStore:
    """Atomic repository-backed store for the latest safe preview manifest."""

    def __init__(self, path: str | Path = DEFAULT_PREVIEW_PATH) -> None:
        self.path = Path(path)

    def load(self) -> PreviewManifest | None:
        if not self.path.exists():
            return None

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"preview store contains invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("preview store must contain a JSON object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported preview schema_version: {payload.get('schema_version')}"
            )
        raw = payload.get("preview")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("preview store preview must be an object or null")
        return PreviewManifest.from_dict(raw)

    def save(self, preview: PreviewManifest | None) -> None:
        if preview is not None and not isinstance(preview, PreviewManifest):
            raise TypeError("preview must be a PreviewManifest or None")

        payload = {
            "schema_version": SCHEMA_VERSION,
            "preview": preview.to_dict() if preview is not None else None,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
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
