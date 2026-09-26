from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .pilot_evidence import PilotFinalEvidence


class PilotEvidenceStore:
    """Atomically persist the immutable final evidence for a production pilot."""

    def __init__(self, path: str | Path = ".autodev/pilot/final-evidence.json") -> None:
        self.path = Path(path)

    def load(self) -> PilotFinalEvidence:
        if not self.path.exists():
            raise FileNotFoundError(f"pilot final evidence not found: {self.path}")
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"pilot final evidence contains invalid JSON: {exc}") from exc
        try:
            return PilotFinalEvidence.from_dict(payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid pilot final evidence payload: {exc}") from exc

    def save(self, evidence: PilotFinalEvidence) -> None:
        if not isinstance(evidence, PilotFinalEvidence):
            raise TypeError(
                f"expected PilotFinalEvidence, got {type(evidence).__name__}"
            )
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
                    evidence.to_dict(),
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
