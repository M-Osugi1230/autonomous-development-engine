from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"
if str(TRUSTED_DIR) not in sys.path:
    sys.path.insert(0, str(TRUSTED_DIR))

from github_client import GitHubClient


class RecordingGitHubClient(GitHubClient):
    def __init__(self, *, repository: str) -> None:
        super().__init__(repository=repository, token="test-token")
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request(self, method: str, path: str, payload: dict | None = None):
        self.calls.append((method, path, payload))
        return {}


class ProjectScopedControlRefTests(unittest.TestCase):
    def test_controller_main_ref_is_rewritten_to_project_control_ref(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GITHUB_REPOSITORY": "M-Osugi1230/autonomous-development-engine",
                "ADE_CONTROL_REF": "ade-jquants",
                "ADE_PROJECT_KEY": "jquants",
            },
            clear=False,
        ):
            client = RecordingGitHubClient(
                repository="M-Osugi1230/autonomous-development-engine"
            )
            self.assertEqual(
                client._effective_controller_ref("main"),
                "ade-jquants",
            )
            self.assertEqual(
                client._effective_controller_ref("explicit-branch"),
                "explicit-branch",
            )

    def test_target_repository_ref_is_not_rewritten(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GITHUB_REPOSITORY": "M-Osugi1230/autonomous-development-engine",
                "ADE_CONTROL_REF": "ade-jquants",
                "ADE_PROJECT_KEY": "jquants",
            },
            clear=False,
        ):
            client = RecordingGitHubClient(
                repository="M-Osugi1230/jquants-research-studio"
            )
            self.assertEqual(client._effective_controller_ref("main"), "main")

    def test_dispatch_inherits_project_scope(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GITHUB_REPOSITORY": "M-Osugi1230/autonomous-development-engine",
                "ADE_CONTROL_REF": "ade-chu-kei",
                "ADE_PROJECT_KEY": "chu-kei",
            },
            clear=False,
        ):
            client = RecordingGitHubClient(
                repository="M-Osugi1230/autonomous-development-engine"
            )
            client.dispatch("ade_next_cycle", {"task_id": "ck-001"})

        self.assertEqual(len(client.calls), 1)
        method, path, payload = client.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            path,
            "/repos/M-Osugi1230/autonomous-development-engine/dispatches",
        )
        self.assertEqual(payload["event_type"], "ade_next_cycle")
        self.assertEqual(payload["client_payload"]["task_id"], "ck-001")
        self.assertEqual(payload["client_payload"]["control_ref"], "ade-chu-kei")
        self.assertEqual(payload["client_payload"]["project_key"], "chu-kei")

    def test_dispatch_does_not_override_explicit_scope(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GITHUB_REPOSITORY": "M-Osugi1230/autonomous-development-engine",
                "ADE_CONTROL_REF": "ade-jquants",
                "ADE_PROJECT_KEY": "jquants",
            },
            clear=False,
        ):
            client = RecordingGitHubClient(
                repository="M-Osugi1230/autonomous-development-engine"
            )
            client.dispatch(
                "ade_next_cycle",
                {
                    "control_ref": "ade-explicit",
                    "project_key": "explicit",
                },
            )

        payload = client.calls[0][2]
        self.assertEqual(payload["client_payload"]["control_ref"], "ade-explicit")
        self.assertEqual(payload["client_payload"]["project_key"], "explicit")


if __name__ == "__main__":
    unittest.main()
