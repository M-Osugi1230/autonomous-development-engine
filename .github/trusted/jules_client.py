from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class JulesError(RuntimeError):
    pass


class JulesUnauthorized(JulesError):
    pass


class JulesQuota(JulesError):
    pass


class JulesPrecondition(JulesError):
    pass


class JulesClient:
    DEFAULT_BASE_URL = "https://jules.googleapis.com/v1alpha"

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
                raise JulesUnauthorized(message) from exc
            if exc.code == 429:
                raise JulesQuota(message) from exc
            if exc.code == 412:
                raise JulesPrecondition(f"HTTP 412: {message}") from exc
            raise JulesError(f"HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise JulesError(f"network error: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JulesError("provider returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise JulesError("provider response must be a JSON object")
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
            raise JulesError("sources response has invalid shape")
        return [item for item in sources if isinstance(item, dict)]

    def find_github_source(self, owner: str, repo: str) -> dict[str, Any] | None:
        for source in self.list_sources():
            github_repo = source.get("githubRepo")
            if not isinstance(github_repo, dict):
                continue
            if github_repo.get("owner") == owner and github_repo.get("repo") == repo:
                return source
        return None

    def create_session(
        self,
        *,
        prompt: str,
        source: str,
        starting_branch: str,
        title: str | None,
        auto_create_pr: bool,
    ) -> dict[str, Any]:
        if not prompt.strip() or not source.strip() or not starting_branch.strip():
            raise ValueError("prompt, source, and starting_branch must be non-empty")
        payload: dict[str, Any] = {
            "prompt": prompt,
            "sourceContext": {
                "source": source,
                "githubRepoContext": {"startingBranch": starting_branch},
            },
            "requirePlanApproval": False,
        }
        if title:
            payload["title"] = title
        if auto_create_pr:
            payload["automationMode"] = "AUTO_CREATE_PR"
        return self._request("POST", "sessions", payload=payload)

    def get_session(self, session_id: str) -> dict[str, Any]:
        normalized = session_id.removeprefix("sessions/")
        if not normalized or "/" in normalized:
            raise ValueError("invalid session_id")
        return self._request("GET", f"sessions/{normalized}")
