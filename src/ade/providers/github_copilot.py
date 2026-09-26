from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .base import ProviderError, ProviderQuotaError, ProviderUnauthorizedError


class GitHubCopilotProvider:
    """GitHub Copilot cloud-agent adapter using the Agent Tasks REST API.

    The caller must provide a user-to-server token with the repository
    "Agent tasks" permission required by GitHub. This adapter never reads
    credentials from environment variables.
    """

    DEFAULT_BASE_URL = "https://api.github.com"
    DEFAULT_API_VERSION = "2026-03-10"

    def __init__(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        base_url: str = DEFAULT_BASE_URL,
        api_version: str = DEFAULT_API_VERSION,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not isinstance(token, str) or not token:
            raise ValueError("token must be a non-empty string")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError("owner must be a non-empty string")
        if not isinstance(repo, str) or not repo.strip():
            raise ValueError("repo must be a non-empty string")
        if not isinstance(api_version, str) or not api_version.strip():
            raise ValueError("api_version must be a non-empty string")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self._token = token
        self._owner = owner.strip()
        self._repo = repo.strip()
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version.strip()
        self._timeout_seconds = float(timeout_seconds)

    @property
    def source_name(self) -> str:
        return f"github/{self._owner}/{self._repo}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, str | int | bool] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urlencode(query)}"

        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": self._api_version,
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
            if exc.code == 429:
                raise ProviderQuotaError(message) from exc
            raise ProviderError(f"HTTP {exc.code}: {message}") from exc
        except URLError as exc:
            raise ProviderError(f"network error: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
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

        message = payload.get("message")
        if isinstance(message, str) and message:
            return message

        error = payload.get("error")
        if isinstance(error, dict):
            nested = error.get("message")
            if isinstance(nested, str) and nested:
                return nested
        return None

    def list_sources(self) -> list[dict[str, Any]]:
        return [
            {
                "name": self.source_name,
                "githubRepo": {
                    "owner": self._owner,
                    "repo": self._repo,
                },
            }
        ]

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
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must not be empty")
        if source != self.source_name:
            raise ValueError(
                f"source must match configured repository source {self.source_name!r}"
            )
        if not isinstance(starting_branch, str) or not starting_branch.strip():
            raise ValueError("starting_branch must not be empty")
        if require_plan_approval:
            raise ProviderError(
                "GitHub Agent Tasks API does not expose ADE plan-approval semantics"
            )

        effective_prompt = prompt.strip()
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise ValueError("title must be a non-empty string or None")
            effective_prompt = f"{title.strip()}\n\n{effective_prompt}"

        task = self._request(
            "POST",
            self._tasks_path(),
            payload={
                "prompt": effective_prompt,
                "base_ref": starting_branch.strip(),
                "create_pull_request": bool(auto_create_pr),
            },
        )
        return self._normalize_task(task)

    def get_session(self, session_id: str) -> dict[str, Any]:
        task_id = self._normalize_task_id(session_id)
        task = self._request(
            "GET",
            f"{self._tasks_path()}/{quote(task_id, safe='')}",
        )
        return self._normalize_task(task)

    def list_activities(self, session_id: str) -> list[dict[str, Any]]:
        task_id = self._normalize_task_id(session_id)
        task = self._request(
            "GET",
            f"{self._tasks_path()}/{quote(task_id, safe='')}",
        )
        activities: list[dict[str, Any]] = []

        state = task.get("state")
        if isinstance(state, str):
            activities.append(
                {
                    "type": "task_state",
                    "state": state,
                    "updated_at": task.get("updated_at"),
                }
            )

        sessions = task.get("sessions", [])
        if isinstance(sessions, list):
            for session in sessions:
                if not isinstance(session, dict):
                    continue
                activities.append(
                    {
                        "type": "session",
                        "id": session.get("id"),
                        "state": session.get("state"),
                        "created_at": session.get("created_at"),
                        "updated_at": session.get("updated_at"),
                        "completed_at": session.get("completed_at"),
                    }
                )
        return activities

    def send_message(self, session_id: str, prompt: str) -> None:
        self._normalize_task_id(session_id)
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must not be empty")
        raise ProviderError(
            "GitHub Agent Tasks REST API does not currently expose a steering-message endpoint"
        )

    def approve_plan(self, session_id: str) -> None:
        self._normalize_task_id(session_id)
        raise ProviderError(
            "GitHub Agent Tasks REST API does not currently expose plan approval"
        )

    def _tasks_path(self) -> str:
        owner = quote(self._owner, safe="")
        repo = quote(self._repo, safe="")
        return f"agents/repos/{owner}/{repo}/tasks"

    def _normalize_task(self, task: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task, dict):
            raise ProviderError("task response must be a JSON object")

        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("task response is missing id")

        state = task.get("state")
        if not isinstance(state, str) or not state:
            raise ProviderError("task response is missing state")

        normalized_state = self._map_state(state)
        html_url = task.get("html_url")
        if not isinstance(html_url, str) or not html_url:
            html_url = None

        outputs: list[dict[str, Any]] = []
        artifacts = task.get("artifacts", [])
        if isinstance(artifacts, list):
            for artifact in artifacts:
                pull_url = self._pull_request_url(artifact)
                if pull_url is not None:
                    outputs.append({"pullRequest": {"url": pull_url}})

        return {
            "id": task_id,
            "name": f"tasks/{task_id}",
            "url": html_url,
            "state": normalized_state,
            "outputs": outputs,
            "providerState": state,
        }

    @staticmethod
    def _map_state(state: str) -> str:
        mapping = {
            "queued": "IN_PROGRESS",
            "in_progress": "IN_PROGRESS",
            "idle": "IN_PROGRESS",
            "completed": "COMPLETED",
            "failed": "FAILED",
            "timed_out": "FAILED",
            "cancelled": "FAILED",
            "waiting_for_user": "AWAITING_USER_FEEDBACK",
        }
        normalized = mapping.get(state)
        if normalized is None:
            raise ProviderError(f"unsupported GitHub agent task state: {state}")
        return normalized

    def _pull_request_url(self, artifact: object) -> str | None:
        if not isinstance(artifact, dict):
            return None
        if artifact.get("provider") != "github" or artifact.get("type") != "pull":
            return None
        data = artifact.get("data")
        if not isinstance(data, dict):
            return None
        pull_id = data.get("id")
        if type(pull_id) is not int or pull_id <= 0:
            return None
        return (
            f"https://github.com/{self._owner}/{self._repo}/pull/{pull_id}"
        )

    @staticmethod
    def _normalize_task_id(session_id: str) -> str:
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        normalized = session_id.removeprefix("tasks/")
        if not normalized or "/" in normalized or normalized != normalized.strip():
            raise ValueError("invalid session_id")
        return normalized
