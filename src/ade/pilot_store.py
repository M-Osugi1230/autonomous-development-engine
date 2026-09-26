from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .pilot import PilotContract


class PilotContractStore:
    """Atomically persist and load a versioned production-pilot contract."""

    def __init__(self, path: str | Path = ".autodev/pilot/contract.json") -> None:
        self.path = Path(path)

    def load(self) -> PilotContract:
        if not self.path.exists():
            raise FileNotFoundError(f"pilot contract file not found: {self.path}")

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"pilot contract contains invalid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("pilot contract file must contain a JSON object")

        try:
            return PilotContract.from_dict(payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"invalid pilot contract payload: {exc}") from exc

    def save(self, contract: PilotContract) -> None:
        if not isinstance(contract, PilotContract):
            raise TypeError(
                f"expected PilotContract, got {type(contract).__name__}"
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
                    contract.to_dict(),
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
