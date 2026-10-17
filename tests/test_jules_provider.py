from __future__ import annotations

import io
import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.error import HTTPError

from ade.providers.base import ProviderQuotaError, ProviderUnauthorizedError
from ade.providers.jules import JulesProvider


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class JulesProviderTests(unittest.TestCase):
    def test_list_sources_and_find_repo(self) -> None:
        response = _FakeResponse(
            {
                "sources": [
                    {
                        "name": "sources/github/example/demo",
                        "githubRepo": {"owner": "example", "repo": "demo"},
                    }
                ]
            }
        )
        provider = JulesProvider(api_key="test-key")

        with patch("ade.providers.jules.urlopen", return_value=response):
            source = provider.find_github_source("example", "demo")

        self.assertIsNotNone(source)
        self.assertEqual(source["name"], "sources/github/example/demo")

    def test_create_session_payload(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            if request.get_method() == "GET" and "/sessions?" in request.full_url:
                return _FakeResponse({"sessions": []})
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse({"id": "123", "state": "QUEUED"})

        provider = JulesProvider(api_key="test-key")
        with patch("ade.providers.jules.urlopen", side_effect=fake_urlopen):
            result = provider.create_session(
                prompt="Do the work",
                source="sources/github/example/demo",
                starting_branch="main",
                title="Demo",
                auto_create_pr=True,
            )

        self.assertEqual(result["id"], "123")
        self.assertEqual(captured["body"]["automationMode"], "AUTO_CREATE_PR")
        self.assertEqual(
            captured["body"]["sourceContext"]["githubRepoContext"]["startingBranch"],
            "main",
        )

    def test_reuses_recent_active_session_instead_of_creating_duplicate(self) -> None:
        created_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        existing = {
            "id": "existing-123",
            "state": "IN_PROGRESS",
            "title": "[ADE:ade-jquants:implementation] Demo",
            "prompt": "Do the work",
            "createTime": created_at,
            "sourceContext": {
                "source": "sources/github/example/demo",
                "githubRepoContext": {"startingBranch": "main"},
            },
        }
        post_calls = 0

        def fake_urlopen(request, timeout):
            nonlocal post_calls
            if request.get_method() == "GET" and "/sessions?" in request.full_url:
                return _FakeResponse({"sessions": [existing]})
            post_calls += 1
            return _FakeResponse({"id": "duplicate", "state": "QUEUED"})

        provider = JulesProvider(api_key="test-key")
        with patch("ade.providers.jules.urlopen", side_effect=fake_urlopen):
            result = provider.create_session(
                prompt="Do the work",
                source="sources/github/example/demo",
                starting_branch="main",
                title="[ADE:ade-jquants:implementation] Demo",
                auto_create_pr=True,
            )

        self.assertEqual(result["id"], "existing-123")
        self.assertEqual(post_calls, 0)

    def test_reuses_recent_completed_session_when_pr_already_exists(self) -> None:
        created_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        existing = {
            "id": "completed-123",
            "state": "COMPLETED",
            "title": "[ADE:ade-jquants:implementation] Demo",
            "prompt": "Do the work",
            "createTime": created_at,
            "sourceContext": {
                "source": "sources/github/example/demo",
                "githubRepoContext": {"startingBranch": "main"},
            },
            "outputs": [
                {
                    "pullRequest": {
                        "url": "https://github.com/example/demo/pull/10"
                    }
                }
            ],
        }
        post_calls = 0

        def fake_urlopen(request, timeout):
            nonlocal post_calls
            if request.get_method() == "GET" and "/sessions?" in request.full_url:
                return _FakeResponse({"sessions": [existing]})
            post_calls += 1
            return _FakeResponse({"id": "duplicate", "state": "QUEUED"})

        provider = JulesProvider(api_key="test-key")
        with patch("ade.providers.jules.urlopen", side_effect=fake_urlopen):
            result = provider.create_session(
                prompt="Do the work",
                source="sources/github/example/demo",
                starting_branch="main",
                title="[ADE:ade-jquants:implementation] Demo",
                auto_create_pr=True,
            )

        self.assertEqual(result["id"], "completed-123")
        self.assertEqual(post_calls, 0)

    def test_completed_session_without_pr_is_not_reused(self) -> None:
        created_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        existing = {
            "id": "completed-no-pr",
            "state": "COMPLETED",
            "title": "[ADE:ade-chu-kei:implementation] Demo",
            "prompt": "Do the work",
            "createTime": created_at,
            "sourceContext": {
                "source": "sources/github/example/demo",
                "githubRepoContext": {"startingBranch": "main"},
            },
            "outputs": [],
        }
        post_calls = 0

        def fake_urlopen(request, timeout):
            nonlocal post_calls
            if request.get_method() == "GET" and "/sessions?" in request.full_url:
                return _FakeResponse({"sessions": [existing]})
            post_calls += 1
            return _FakeResponse({"id": "replacement", "state": "QUEUED"})

        provider = JulesProvider(api_key="test-key")
        with patch("ade.providers.jules.urlopen", side_effect=fake_urlopen):
            result = provider.create_session(
                prompt="Do the work",
                source="sources/github/example/demo",
                starting_branch="main",
                title="[ADE:ade-chu-kei:implementation] Demo",
                auto_create_pr=True,
            )

        self.assertEqual(result["id"], "replacement")
        self.assertEqual(post_calls, 1)

    def test_stale_completed_session_is_not_reused(self) -> None:
        created_at = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        existing = {
            "id": "stale-123",
            "state": "COMPLETED",
            "title": "Demo",
            "prompt": "Do the work",
            "createTime": created_at,
            "outputs": [
                {"pullRequest": {"url": "https://github.com/example/demo/pull/9"}}
            ],
        }

        def fake_urlopen(request, timeout):
            if request.get_method() == "GET" and "/sessions?" in request.full_url:
                return _FakeResponse({"sessions": [existing]})
            return _FakeResponse({"id": "fresh-123", "state": "QUEUED"})

        provider = JulesProvider(api_key="test-key")
        with patch("ade.providers.jules.urlopen", side_effect=fake_urlopen):
            result = provider.create_session(
                prompt="Do the work",
                source="sources/github/example/demo",
                starting_branch="main",
                title="Demo",
                auto_create_pr=True,
            )

        self.assertEqual(result["id"], "fresh-123")

    def test_unauthorized_is_mapped(self) -> None:
        body = io.BytesIO(json.dumps({"error": {"message": "bad key"}}).encode("utf-8"))
        error = HTTPError("url", 401, "Unauthorized", hdrs=None, fp=body)
        provider = JulesProvider(api_key="test-key")

        with patch("ade.providers.jules.urlopen", side_effect=error):
            with self.assertRaisesRegex(ProviderUnauthorizedError, "bad key"):
                provider.list_sources()

    def test_precondition_capacity_is_mapped_to_quota(self) -> None:
        body = io.BytesIO(
            json.dumps(
                {"error": {"message": "Precondition check failed."}}
            ).encode("utf-8")
        )
        error = HTTPError(
            "url",
            400,
            "Bad Request",
            hdrs=None,
            fp=body,
        )
        provider = JulesProvider(api_key="test-key")

        with patch("ade.providers.jules.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                ProviderQuotaError,
                "Precondition check failed",
            ):
                provider.list_sources()

    def test_quota_is_mapped(self) -> None:
        body = io.BytesIO(
            json.dumps({"error": {"message": "quota exceeded"}}).encode("utf-8")
        )
        error = HTTPError("url", 429, "Too Many Requests", hdrs=None, fp=body)
        provider = JulesProvider(api_key="test-key")

        with patch("ade.providers.jules.urlopen", side_effect=error):
            with self.assertRaisesRegex(ProviderQuotaError, "quota exceeded"):
                provider.list_sources()


if __name__ == "__main__":
    unittest.main()
