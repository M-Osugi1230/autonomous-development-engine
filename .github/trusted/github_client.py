from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(
        self,
        *,
        repository: str | None = None,
        token: str | None = None,
        api_url: str = "https://api.github.com",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if "/" not in self.repository:
            raise ValueError("GITHUB_REPOSITORY must be owner/name")
        if not self.token:
            raise ValueError("GITHUB_TOKEN is required")
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.api_url}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise GitHubError(f"GitHub HTTP {exc.code}: {raw[:1000]}") from exc
        except URLError as exc:
            raise GitHubError(f"GitHub network error: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GitHubError("GitHub returned invalid JSON") from exc

    def get_pull_request(self, number: int) -> dict[str, Any]:
        payload = self._request("GET", f"/repos/{self.repository}/pulls/{number}")
        if not isinstance(payload, dict):
            raise GitHubError("pull request response must be an object")
        return payload

    def list_pull_request_files(self, number: int) -> list[dict[str, Any]]:
        payload = self._request(
            "GET", f"/repos/{self.repository}/pulls/{number}/files?per_page=100"
        )
        if not isinstance(payload, list):
            raise GitHubError("pull request files response must be a list")
        return [item for item in payload if isinstance(item, dict)]

    def merge_pull_request(self, number: int, *, expected_sha: str) -> dict[str, Any]:
        payload = self._request(
            "PUT",
            f"/repos/{self.repository}/pulls/{number}/merge",
            {
                "sha": expected_sha,
                "merge_method": "squash",
                "commit_title": f"ADE autonomous merge: PR #{number}",
            },
        )
        if not isinstance(payload, dict):
            raise GitHubError("merge response must be an object")
        return payload

    def get_json_file(self, path: str, *, ref: str = "main") -> tuple[dict[str, Any], str]:
        payload = self._request(
            "GET", f"/repos/{self.repository}/contents/{path}?ref={ref}"
        )
        if not isinstance(payload, dict):
            raise GitHubError(f"{path} response must be an object")
        encoded = payload.get("content")
        sha = payload.get("sha")
        if not isinstance(encoded, str) or not isinstance(sha, str):
            raise GitHubError(f"{path} is missing content or sha")
        try:
            raw = base64.b64decode(encoded.replace("\n", ""))
            decoded = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubError(f"{path} is not valid UTF-8 JSON") from exc
        if not isinstance(decoded, dict):
            raise GitHubError(f"{path} must contain a JSON object")
        return decoded, sha

    def put_json_file(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        sha: str | None,
        message: str,
        branch: str = "main",
    ) -> None:
        content = json.dumps(
            payload, indent=2, ensure_ascii=False, sort_keys=True
        ) + "\n"
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        request_payload: dict[str, Any] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha is not None:
            request_payload["sha"] = sha
        self._request(
            "PUT",
            f"/repos/{self.repository}/contents/{path}",
            request_payload,
        )

    def upsert_json_file(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        message: str,
        branch: str = "main",
    ) -> None:
        sha: str | None = None
        try:
            _, sha = self.get_json_file(path, ref=branch)
        except GitHubError as exc:
            if "GitHub HTTP 404:" not in str(exc):
                raise
        self.put_json_file(
            path,
            payload,
            sha=sha,
            message=message,
            branch=branch,
        )

    def dispatch(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self._request(
            "POST",
            f"/repos/{self.repository}/dispatches",
            {"event_type": event_type, "client_payload": payload or {}},
        )
