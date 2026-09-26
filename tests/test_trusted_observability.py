from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_modules():
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        import github_client  # type: ignore

        path = TRUSTED_DIR / "observability.py"
        spec = importlib.util.spec_from_file_location(
            "trusted_observability_test_module",
            path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load trusted observability.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module, github_client
    finally:
        sys.path.pop(0)


class FakeApi:
    def __init__(self, github_error):
        self.github_error = github_error
        self.files = {}
        self.put_calls = []
        self.upsert_calls = []

    def get_json_file(self, path, *, ref="main"):
        if path not in self.files:
            raise self.github_error("GitHub HTTP 404: not found")
        payload, sha = self.files[path]
        return copy.deepcopy(payload), sha

    def put_json_file(self, path, payload, *, sha, message, branch="main"):
        self.put_calls.append(
            {
                "path": path,
                "payload": copy.deepcopy(payload),
                "sha": sha,
                "message": message,
                "branch": branch,
            }
        )
        self.files[path] = (copy.deepcopy(payload), "new-sha")

    def upsert_json_file(self, path, payload, *, message, branch="main"):
        self.upsert_calls.append(
            {
                "path": path,
                "payload": copy.deepcopy(payload),
                "message": message,
                "branch": branch,
            }
        )
        self.files[path] = (copy.deepcopy(payload), "new-sha")


class TrustedObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module, github_client = load_modules()
        self.api = FakeApi(github_client.GitHubError)

    def test_append_creates_store_and_is_idempotent(self) -> None:
        created = self.module.append_activity(
            self.api,
            event_id="evt-1",
            kind="PR_MERGED",
            occurred_at="2026-09-26T01:40:00+00:00",
            summary="Merged Jules PR #40",
            task_id="vertical-slice-040",
        )
        self.assertTrue(created)
        self.assertEqual(len(self.api.put_calls), 1)
        payload = self.api.put_calls[0]["payload"]
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["events"][0]["event_id"], "evt-1")

        created_again = self.module.append_activity(
            self.api,
            event_id="evt-1",
            kind="PR_MERGED",
            occurred_at="2026-09-26T01:40:00+00:00",
            summary="Merged Jules PR #40",
            task_id="vertical-slice-040",
        )
        self.assertFalse(created_again)
        self.assertEqual(len(self.api.put_calls), 1)

    def test_conflicting_event_id_is_rejected(self) -> None:
        self.module.append_activity(
            self.api,
            event_id="evt-1",
            kind="PR_MERGED",
            occurred_at="2026-09-26T01:40:00+00:00",
            summary="Merged Jules PR #40",
            task_id="vertical-slice-040",
        )
        with self.assertRaises(ValueError):
            self.module.append_activity(
                self.api,
                event_id="evt-1",
                kind="TASK_COMPLETED",
                occurred_at="2026-09-26T01:40:00+00:00",
                summary="Changed meaning",
                task_id="vertical-slice-040",
            )

    def test_preview_rejects_untrusted_url_and_secret_text(self) -> None:
        with self.assertRaises(ValueError):
            self.module.set_preview(
                self.api,
                preview_id="bad",
                kind="PULL_REQUEST",
                title="bad",
                url="https://example.com/pull/1",
                task_id="task-1",
                updated_at="2026-09-26T01:40:00+00:00",
            )
        with self.assertRaises(ValueError):
            self.module.append_activity(
                self.api,
                event_id="secret",
                kind="SYSTEM",
                occurred_at="2026-09-26T01:40:00+00:00",
                summary="ghp_123456789012345678901234567890123456",
            )

    def test_record_merged_pr_writes_activity_and_latest_preview(self) -> None:
        self.module.record_merged_pr(
            self.api,
            pr_number=40,
            pr_url="https://github.com/M-Osugi1230/autonomous-development-engine/pull/40",
            task_id="vertical-slice-040",
            head_sha="abcdef1234567890",
            occurred_at="2026-09-26T01:40:00+00:00",
        )

        activity = self.api.files[self.module.ACTIVITY_PATH][0]
        preview = self.api.files[self.module.PREVIEW_PATH][0]
        self.assertEqual(activity["events"][0]["kind"], "PR_MERGED")
        self.assertEqual(
            activity["events"][0]["event_id"],
            "pr-merged-40-abcdef123456",
        )
        self.assertEqual(preview["preview"]["kind"], "PULL_REQUEST")
        self.assertEqual(preview["preview"]["task_id"], "vertical-slice-040")
        self.assertEqual(
            preview["preview"]["url"],
            "https://github.com/M-Osugi1230/autonomous-development-engine/pull/40",
        )


if __name__ == "__main__":
    unittest.main()
