from __future__ import annotations

import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"
if str(TRUSTED_DIR) not in sys.path:
    sys.path.insert(0, str(TRUSTED_DIR))

from github_client import GitHubClient, GitHubError
from ade.infrastructure_retry import RetryPolicy


class FakeGitHubClient(GitHubClient):
    def __init__(self, *, reads, write_errors):
        self.retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.01)
        self.reads = list(reads)
        self.write_errors = list(write_errors)
        self.put_calls = []
        self.sleeps = []
        self.sleep = self.sleeps.append

    def get_json_file(self, path: str, *, ref: str = "main"):
        if not self.reads:
            raise AssertionError("unexpected get_json_file call")
        item = self.reads.pop(0)
        if item is None:
            raise GitHubError("GitHub HTTP 404: missing")
        return item

    def put_json_file(
        self,
        path: str,
        payload: dict,
        *,
        sha: str | None,
        message: str,
        branch: str = "main",
    ) -> None:
        self.put_calls.append(
            {
                "path": path,
                "payload": payload,
                "sha": sha,
                "message": message,
                "branch": branch,
            }
        )
        if not self.write_errors:
            return
        error = self.write_errors.pop(0)
        if error is not None:
            raise GitHubError(error)


class GitHubJsonUpsertConflictTests(unittest.TestCase):
    def test_retries_branch_level_409_when_exact_file_is_unchanged(self) -> None:
        old = {"status": "ARMED"}
        desired = {"status": "DISPATCHED"}
        sha = "a" * 40
        client = FakeGitHubClient(
            reads=[(old, sha), (old, sha)],
            write_errors=["GitHub HTTP 409: branch moved", None],
        )

        client.upsert_json_file(
            ".autodev/runtime-verification/task/receipt.json",
            desired,
            message="runtime: dispatched",
        )

        self.assertEqual(len(client.put_calls), 2)
        self.assertEqual(client.put_calls[0]["sha"], sha)
        self.assertEqual(client.put_calls[1]["sha"], sha)
        self.assertEqual(client.sleeps, [0.01])

    def test_refuses_to_overwrite_concurrent_same_file_mutation(self) -> None:
        sha_a = "a" * 40
        sha_b = "b" * 40
        client = FakeGitHubClient(
            reads=[
                ({"status": "ARMED"}, sha_a),
                ({"status": "HUMAN_WAIT"}, sha_b),
            ],
            write_errors=["GitHub HTTP 409: branch moved"],
        )

        with self.assertRaisesRegex(
            GitHubError,
            "concurrent JSON file mutation detected",
        ):
            client.upsert_json_file(
                ".autodev/runtime-verification/task/receipt.json",
                {"status": "DISPATCHED"},
                message="runtime: dispatched",
            )

        self.assertEqual(len(client.put_calls), 1)
        self.assertEqual(client.sleeps, [0.01])

    def test_identical_concurrent_create_is_idempotent_success(self) -> None:
        desired = {"schema_version": 1, "status": "VERIFIED"}
        client = FakeGitHubClient(
            reads=[None, (desired, "c" * 40)],
            write_errors=["GitHub HTTP 409: branch moved"],
        )

        client.upsert_json_file(
            ".autodev/runtime-verification/task/report.json",
            desired,
            message="runtime: report",
        )

        self.assertEqual(len(client.put_calls), 1)
        self.assertEqual(client.sleeps, [0.01])


if __name__ == "__main__":
    unittest.main()
