from __future__ import annotations

import base64
import json
import os
import time
import re
from typing import Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from ade.infrastructure_retry import InfrastructureFailure, RetryPolicy, classify_github_error, retry_delay
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class GitHubError(RuntimeError):
    pass


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class GitHubClient:
    def __init__(
        self,
        *,
        repository: str | None = None,
        token: str | None = None,
        api_url: str = "https://api.github.com",
        timeout_seconds: float = 30.0,
        retry_policy: RetryPolicy | None = None,
        sleep=time.sleep,
    ) -> None:
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if "/" not in self.repository:
            raise ValueError("GITHUB_REPOSITORY must be owner/name")
        if not self.token:
            raise ValueError("GITHUB_TOKEN is required")
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep = sleep

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        last_error: GitHubError | None = None
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                return self._request_once(method, path, payload)
            except GitHubError as exc:
                last_error = exc
                if classify_github_error(str(exc)) != InfrastructureFailure.RETRYABLE or attempt >= self.retry_policy.max_attempts:
                    raise
                self.sleep(retry_delay(self.retry_policy, attempt))
        assert last_error is not None
        raise last_error

    def _request_once(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.api_url}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}", "X-GitHub-Api-Version": "2022-11-28"}
        if body is not None: headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response: raw = response.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace"); raise GitHubError(f"GitHub HTTP {exc.code}: {raw[:1000]}") from exc
        except URLError as exc: raise GitHubError(f"GitHub network error: {exc.reason}") from exc
        if not raw: return {}
        try: return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc: raise GitHubError("GitHub returned invalid JSON") from exc

    @staticmethod
    def _validate_repository_name(repository: str) -> str:
        if not isinstance(repository, str) or _REPOSITORY.fullmatch(repository) is None:
            raise ValueError("repository must be owner/name")
        return repository

    def get_branch_head_sha(
        self,
        repository: str,
        *,
        branch: str = "main",
    ) -> str:
        repository = self._validate_repository_name(repository)
        if (
            not isinstance(branch, str)
            or not branch.strip()
            or "/" in branch
            or len(branch.strip()) > 120
        ):
            raise ValueError("branch must be a simple non-empty name")
        payload = self._request(
            "GET",
            f"/repos/{repository}/branches/{branch.strip()}",
        )
        if not isinstance(payload, dict):
            raise GitHubError("branch response must be an object")
        commit = payload.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or _SHA40.fullmatch(sha) is None:
            raise GitHubError("branch response has no valid head SHA")
        return sha

    def list_tree_paths(
        self,
        repository: str,
        *,
        tree_sha: str,
        max_entries: int = 5000,
    ) -> list[str]:
        repository = self._validate_repository_name(repository)
        if not isinstance(tree_sha, str) or _SHA40.fullmatch(tree_sha) is None:
            raise ValueError("tree_sha must be a lowercase 40-char SHA")
        if type(max_entries) is not int or max_entries < 1 or max_entries > 20000:
            raise ValueError("max_entries must be between 1 and 20000")

        payload = self._request(
            "GET",
            f"/repos/{repository}/git/trees/{tree_sha}?recursive=1",
        )
        if not isinstance(payload, dict):
            raise GitHubError("tree response must be an object")
        if payload.get("truncated") is True:
            raise GitHubError("repository tree was truncated")
        tree = payload.get("tree")
        if not isinstance(tree, list):
            raise GitHubError("repository tree response has no tree list")

        paths: list[str] = []
        for entry in tree:
            if not isinstance(entry, dict) or entry.get("type") != "blob":
                continue
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                raise GitHubError("repository tree contains an invalid blob path")
            paths.append(path)
            if len(paths) > max_entries:
                raise GitHubError("repository tree exceeds trusted entry budget")
        return paths

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
