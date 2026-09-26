from __future__ import annotations

import io
import json
import unittest
from urllib.error import HTTPError

from ade import GitHubCopilotProvider
from ade.providers import ProviderError, ProviderQuotaError, ProviderUnauthorizedError
import ade.providers.github_copilot as github_copilot_module


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._raw


def http_error(code: int, message: str) -> HTTPError:
    return HTTPError(
        url="https://api.github.com/example",
        code=code,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(json.dumps({"message": message}).encode("utf-8")),
    )


class GitHubCopilotProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = GitHubCopilotProvider(
            token="test-token",
            owner="octo",
            repo="repo",
            base_url="https://api.github.test",
        )
        self.original_urlopen = github_copilot_module.urlopen

    def tearDown(self) -> None:
        github_copilot_module.urlopen = self.original_urlopen

    def test_list_sources_is_repository_scoped(self) -> None:
        self.assertEqual(
            self.provider.list_sources(),
            [
                {
                    "name": "github/octo/repo",
                    "githubRepo": {"owner": "octo", "repo": "repo"},
                }
            ],
        )

    def test_create_session_uses_agent_tasks_api_and_normalizes_response(self) -> None:
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["method"] = request.get_method()
            seen["headers"] = dict(request.header_items())
            seen["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                {
                    "id": "task-123",
                    "html_url": "https://github.com/octo/repo/copilot/tasks/task-123",
                    "state": "queued",
                    "artifacts": [],
                }
            )

        github_copilot_module.urlopen = fake_urlopen
        result = self.provider.create_session(
            prompt="Implement the feature",
            source="github/octo/repo",
            starting_branch="main",
            title="Feature task",
            auto_create_pr=True,
            require_plan_approval=False,
        )

        self.assertEqual(
            seen["url"],
            "https://api.github.test/agents/repos/octo/repo/tasks",
        )
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["headers"]["X-github-api-version"], "2026-03-10")
        self.assertEqual(seen["payload"]["base_ref"], "main")
        self.assertTrue(seen["payload"]["create_pull_request"])
        self.assertEqual(
            seen["payload"]["prompt"],
            "Feature task\n\nImplement the feature",
        )
        self.assertEqual(result["id"], "task-123")
        self.assertEqual(result["state"], "IN_PROGRESS")
        self.assertEqual(result["providerState"], "queued")

    def test_completed_task_exposes_pull_request_url(self) -> None:
        def fake_urlopen(request, timeout):
            return FakeResponse(
                {
                    "id": "task-456",
                    "html_url": "https://github.com/octo/repo/copilot/tasks/task-456",
                    "state": "completed",
                    "artifacts": [
                        {
                            "provider": "github",
                            "type": "pull",
                            "data": {"id": 77},
                        }
                    ],
                }
            )

        github_copilot_module.urlopen = fake_urlopen
        result = self.provider.get_session("task-456")

        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(
            result["outputs"],
            [{"pullRequest": {"url": "https://github.com/octo/repo/pull/77"}}],
        )

    def test_waiting_for_user_maps_to_explicit_human_feedback_state(self) -> None:
        def fake_urlopen(request, timeout):
            return FakeResponse(
                {
                    "id": "task-wait",
                    "state": "waiting_for_user",
                    "artifacts": [],
                }
            )

        github_copilot_module.urlopen = fake_urlopen
        result = self.provider.get_session("task-wait")
        self.assertEqual(result["state"], "AWAITING_USER_FEEDBACK")

    def test_failed_timed_out_and_cancelled_are_terminal_failures(self) -> None:
        for provider_state in ("failed", "timed_out", "cancelled"):
            with self.subTest(provider_state=provider_state):
                def fake_urlopen(request, timeout, state=provider_state):
                    return FakeResponse(
                        {"id": "task-x", "state": state, "artifacts": []}
                    )

                github_copilot_module.urlopen = fake_urlopen
                result = self.provider.get_session("task-x")
                self.assertEqual(result["state"], "FAILED")

    def test_activity_projection_uses_task_and_session_states(self) -> None:
        def fake_urlopen(request, timeout):
            return FakeResponse(
                {
                    "id": "task-activity",
                    "state": "in_progress",
                    "updated_at": "2026-09-26T12:00:00Z",
                    "sessions": [
                        {
                            "id": "session-1",
                            "state": "in_progress",
                            "created_at": "2026-09-26T11:55:00Z",
                            "updated_at": "2026-09-26T12:00:00Z",
                            "completed_at": None,
                        }
                    ],
                }
            )

        github_copilot_module.urlopen = fake_urlopen
        activities = self.provider.list_activities("task-activity")
        self.assertEqual(activities[0]["type"], "task_state")
        self.assertEqual(activities[1]["type"], "session")
        self.assertEqual(activities[1]["id"], "session-1")

    def test_plan_approval_and_steering_are_explicitly_unsupported(self) -> None:
        with self.assertRaises(ProviderError):
            self.provider.create_session(
                prompt="x",
                source="github/octo/repo",
                starting_branch="main",
                require_plan_approval=True,
            )
        with self.assertRaises(ProviderError):
            self.provider.send_message("task-1", "continue")
        with self.assertRaises(ProviderError):
            self.provider.approve_plan("task-1")

    def test_http_errors_map_to_provider_contract(self) -> None:
        cases = [
            (401, ProviderUnauthorizedError),
            (403, ProviderUnauthorizedError),
            (429, ProviderQuotaError),
            (422, ProviderError),
        ]
        for code, expected in cases:
            with self.subTest(code=code):
                def failing_urlopen(*args, code=code, **kwargs):
                    raise http_error(code, f"error-{code}")

                github_copilot_module.urlopen = failing_urlopen
                with self.assertRaises(expected):
                    self.provider.get_session("task-1")

    def test_validation_rejects_wrong_source_and_invalid_session_id(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.create_session(
                prompt="x",
                source="github/other/repo",
                starting_branch="main",
            )
        with self.assertRaises(ValueError):
            self.provider.get_session("tasks/a/b")

    def test_constructor_requires_explicit_token(self) -> None:
        with self.assertRaises(ValueError):
            GitHubCopilotProvider(token="", owner="octo", repo="repo")


if __name__ == "__main__":
    unittest.main()
