from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .pilot import PilotContract
from .pilot_activation import (
    PilotActivation,
    pilot_target_writes_allowed,
    require_pilot_target_write_activation,
)


class PilotActivationStore:
    """Atomically persist and enforce the production-pilot human activation."""

    def __init__(self, path: str | Path = ".autodev/pilot/activation.json") -> None:
        self.path = Path(path)

    def load(self) -> PilotActivation | None:
        if not self.path.exists():
            return None

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"pilot activation contains invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("pilot activation file must contain a JSON object")

        try:
            return PilotActivation.from_dict(payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid pilot activation payload: {exc}") from exc

    def save(self, activation: PilotActivation) -> None:
        if not isinstance(activation, PilotActivation):
            raise TypeError(
                f"expected PilotActivation, got {type(activation).__name__}"
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
                    activation.to_dict(),
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

    def target_writes_allowed(self, contract: PilotContract) -> bool:
        return pilot_target_writes_allowed(contract, self.load())

    def require_target_write_activation(self, contract: PilotContract) -> None:
        require_pilot_target_write_activation(contract, self.load())
