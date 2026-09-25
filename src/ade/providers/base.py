from __future__ import annotations

from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Base provider failure."""


class ProviderUnauthorizedError(ProviderError):
    """Authentication or authorization failed."""


class ProviderQuotaError(ProviderError):
    """Provider quota or rate limit was reached."""


class CodingAgentProvider(Protocol):
    def list_sources(self) -> list[dict[str, Any]]:
        ...

    def create_session(
        self,
        *,
        prompt: str,
        source: str,
        starting_branch: str,
        title: str | None = None,
        auto_create_pr: bool = False,
        require_plan_approval: bool = False,
    ) -> dict[str, Any]:
        ...

    def get_session(self, session_id: str) -> dict[str, Any]:
        ...

    def list_activities(self, session_id: str) -> list[dict[str, Any]]:
        ...

    def send_message(self, session_id: str, prompt: str) -> None:
        ...

    def approve_plan(self, session_id: str) -> None:
        ...
