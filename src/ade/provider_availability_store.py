from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .provider_availability import ProviderAvailabilityState


DEFAULT_PROVIDER_AVAILABILITY_PATH = Path(
    ".autodev/provider-availability.json"
)


class ProviderAvailabilityStore:
    def __init__(
        self,
        path: str | Path = DEFAULT_PROVIDER_AVAILABILITY_PATH,
    ) -> None:
        self.path = Path(path)

    def load(self) -> ProviderAvailabilityState:
        if not self.path.exists():
            raise FileNotFoundError(
                f"provider availability file not found: {self.path}"
            )

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"provider availability file contains invalid JSON: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise ValueError(
                "provider availability file must contain a JSON object"
            )

        try:
            return ProviderAvailabilityState.from_dict(payload)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(
                f"invalid provider availability payload: {exc}"
            ) from exc

    def load_or_empty(self) -> ProviderAvailabilityState:
        try:
            return self.load()
        except FileNotFoundError:
            return ProviderAvailabilityState()

    def save(self, state: ProviderAvailabilityState) -> None:
        if not isinstance(state, ProviderAvailabilityState):
            raise TypeError(
                "state must be a ProviderAvailabilityState"
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
                    state.to_dict(),
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
