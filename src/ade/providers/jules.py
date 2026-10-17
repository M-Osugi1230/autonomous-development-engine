from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import ProviderError, ProviderQuotaError, ProviderUnauthorizedError


class JulesProvider:
    """Minimal Jules REST API adapter for ADE."""

    DEFAULT_BASE_URL = "https://jules.googleapis.com/v1alpha"
    SESSION_REUSE_WINDOW = timedelta(hours=2)

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        key = api_key or os.environ.get("JULES_API_KEY")
        if not key:
            raise ValueError("JULES_API_KEY is required")
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"

        body = None
        headers = {
            "x-goog-api-key": self._api_key,
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url=url, data=body, headers=headers, method=method.upper())

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read()
            message = self._extract_error_message(raw) or f"HTTP {exc.code}"
            if exc.code in (401, 403):
                raise ProviderUnauthorizedError(message) from exc
            if exc.code == 429 or (
                exc.code == 400
                and message.strip().casefold() == "precondition check failed."
            ):
                raise ProviderQuotaError(message) from exc
            raise ProviderError(message) from exc
        except URLError as exc:
            raise ProviderError(f"network error: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderError("provider returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ProviderError("provider response must be a JSON object")
        return decoded

    @staticmethod
    def _extract_error_message(raw: bytes) -> str | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        return None

    def list_sources(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "sources")
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            raise ProviderError("sources response has invalid shape")
        return [item for item in sources if isinstance(item, dict)]

    def list_sessions(
        self,
        *,
        page_size: int = 100,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be an integer between 1 and 100")
        if type(max_pages) is not int or max_pages < 1:
            raise ValueError("max_pages must be a positive integer")

        sessions: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(max_pages):
            query: dict[str, str | int] = {"pageSize": page_size}
            if page_token:
                query["pageToken"] = page_token
            payload = self._request("GET", "sessions", query=query)
            page = payload.get("sessions", [])
            if not isinstance(page, list):
                raise ProviderError("sessions response has invalid shape")
            sessions.extend(item for item in page if isinstance(item, dict))

            token = payload.get("nextPageToken")
            if token is None or token == "":
                return sessions
            if not isinstance(token, str):
                raise ProviderError("sessions nextPageToken has invalid shape")
            page_token = token

        return sessions

    def find_github_source(self, owner: str, repo: str) -> dict[str, Any] | None:
        for source in self.list_sources():
            github_repo = source.get("githubRepo")
            if not isinstance(github_repo, dict):
                continue
            if github_repo.get("owner") == owner and github_repo.get("repo") == repo:
                return source
        return None

    @staticmethod
    def _session_time(session: dict[str, Any]) -> datetime | None:
        for key in ("createTime", "createdAt", "created_at"):
            raw = session.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                continue
            return parsed.astimezone(UTC)
        return None

    @staticmethod
    def _pull_request_url(session: dict[str, Any]) -> str | None:
        outputs = session.get("outputs")
        if not isinstance(outputs, list):
            return None
        for output in outputs:
            if not isinstance(output, dict):
                continue
            pull_request = output.get("pullRequest")
            if not isinstance(pull_request, dict):
                continue
            url = pull_request.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()
        return None

    @staticmethod
    def _source_matches(
        session: dict[str, Any],
        *,
        source: str,
        starting_branch: str,
    ) -> bool:
        context = session.get("sourceContext")
        if not isinstance(context, dict):
            return True
        observed_source = context.get("source")
        if isinstance(observed_source, str) and observed_source != source:
            return False
        repo_context = context.get("githubRepoContext")
        if not isinstance(repo_context, dict):
            return True
        observed_branch = repo_context.get("startingBranch")
        return not isinstance(observed_branch, str) or observed_branch == starting_branch

    def _reusable_session(
        self,
        *,
        prompt: str,
        source: str,
        starting_branch: str,
        title: str | None,
    ) -> dict[str, Any] | None:
        if not title:
            return None

        now = datetime.now(UTC)
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for session in self.list_sessions(page_size=100, max_pages=3):
            if session.get("title") != title:
                continue
            observed_prompt = session.get("prompt")
            if (
                isinstance(observed_prompt, str)
                and observed_prompt.strip()
                and observed_prompt != prompt
            ):
                continue
            if not self._source_matches(
                session,
                source=source,
                starting_branch=starting_branch,
            ):
                continue

            created_at = self._session_time(session)
            if created_at is None or now - created_at > self.SESSION_REUSE_WINDOW:
                continue

            state = session.get("state")
            if not isinstance(state, str) or not state.strip():
                continue
            state = state.strip().upper()
            if state in {"FAILED", "CANCELLED", "CANCELED"}:
                continue
            if state == "COMPLETED" and self._pull_request_url(session) is None:
                continue
            candidates.append((created_at, session))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

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
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if not source.strip():
            raise ValueError("source must not be empty")
        if not starting_branch.strip():
            raise ValueError("starting_branch must not be empty")

        reusable = self._reusable_session(
            prompt=prompt,
            source=source,
            starting_branch=starting_branch,
            title=title,
        )
        if reusable is not None:
            return reusable

        payload: dict[str, Any] = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {"startingBranch": starting_branch},
            },
            "requirePlanApproval": require_plan_approval,
        }
        if title:
            payload["title"] = title
        if auto_create_pr:
            payload["automationMode"] = "AUTO_CREATE_PR"

        return self._request("POST", "sessions", payload=payload)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"sessions/{self._normalize_session_id(session_id)}")

    def list_activities(self, session_id: str, *, page_size: int = 50) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            f"sessions/{self._normalize_session_id(session_id)}/activities",
            query={"pageSize": page_size},
        )
        activities = payload.get("activities", [])
        if not isinstance(activities, list):
            raise ProviderError("activities response has invalid shape")
        return [item for item in activities if isinstance(item, dict)]

    def send_message(self, session_id: str, prompt: str) -> None:
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        self._request(
            "POST",
            f"sessions/{self._normalize_session_id(session_id)}:sendMessage",
            payload={"prompt": prompt},
        )

    def approve_plan(self, session_id: str) -> None:
        self._request(
            "POST",
            f"sessions/{self._normalize_session_id(session_id)}:approvePlan",
            payload={},
        )

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        normalized = session_id.removeprefix("sessions/")
        if not normalized or "/" in normalized:
            raise ValueError("invalid session_id")
        return normalized
