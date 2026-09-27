from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .campaign import AutonomousCampaign

DEFAULT_CAMPAIGN_PATH = Path(".autodev/campaign.json")


class CampaignStore:
    """Load and atomically persist ADE autonomous campaigns."""

    def __init__(self, path: str | Path = DEFAULT_CAMPAIGN_PATH) -> None:
        self.path = Path(path)

    def load(self) -> AutonomousCampaign:
        if not self.path.exists():
            raise FileNotFoundError(f"campaign file not found: {self.path}")

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as err:
            raise ValueError(f"campaign file contains invalid JSON: {err}") from err

        if not isinstance(payload, dict):
            raise ValueError("campaign file must contain a JSON object")

        try:
            return AutonomousCampaign.from_dict(payload)
        except (ValueError, TypeError, KeyError) as err:
            raise ValueError(f"invalid campaign payload: {err}") from err

    def save(self, campaign: AutonomousCampaign) -> None:
        if not isinstance(campaign, AutonomousCampaign):
            raise TypeError(f"expected AutonomousCampaign, got {type(campaign).__name__}")

        payload = campaign.to_dict()
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
