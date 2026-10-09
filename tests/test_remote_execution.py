from __future__ import annotations

import unittest

from ade.remote_execution import (
    RemoteExecutionReceipt,
    execution_target_from_state,
    parse_pull_request_url,
    pull_request_is_trusted_noop,
    receipt_binds_pull_request,
)


class RemoteExecutionTests(unittest.TestCase):
    def test_execution_target_defaults_to_controller_repository(self) -> None:
        state = {"metadata": {}}
        self.assertEqual(
            execution_target_from_state(
                state,
                fallback_repository="M-Osugi1230/autonomous-development-engine",
            ),
            "M-Osugi1230/autonomous-development-engine",
        )

    def test_execution_target_uses_planner_target_repository(self) -> None:
        state = {
            "metadata": {
                "target_repository": "M-Osugi1230/one-minute-thought-experiments"
            }
        }
        self.assertEqual(
            execution_target_from_state(
                state,
                fallback_repository="M-Osugi1230/autonomous-development-engine",
            ),
            "M-Osugi1230/one-minute-thought-experiments",
        )

    def test_unsafe_repository_name_is_rejected(self) -> None:
        state = {"metadata": {"target_repository": "../other"}}
        with self.assertRaisesRegex(ValueError, "owner/name"):
            execution_target_from_state(
                state,
                fallback_repository="M-Osugi1230/autonomous-development-engine",
            )

    def test_pull_request_url_is_strictly_parsed(self) -> None:
        repository, number = parse_pull_request_url(
            "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
        )
        self.assertEqual(repository, "M-Osugi1230/one-minute-thought-experiments")
        self.assertEqual(number, 7)

        for invalid in (
            "http://github.com/a/b/pull/1",
            "https://example.com/a/b/pull/1",
            "https://github.com/a/b/issues/1",
            "https://github.com/a/b/pull/nope",
            "https://github.com/a/b/pull/1?x=y",
        ):
            with self.assertRaises(ValueError):
                parse_pull_request_url(invalid)

    def test_trusted_noop_accepts_jules_zero_diff_open_or_closed_pr(self) -> None:
        base = {
            "body": (
                "Verified the existing implementation.\n\n---\n"
                "*PR created automatically by Jules for task [123](https://jules.google.com/task/123)*"
            ),
            "changed_files": 0,
            "additions": 0,
            "deletions": 0,
            "merged_at": None,
        }
        for state in ("open", "closed"):
            payload = dict(base, state=state)
            self.assertTrue(pull_request_is_trusted_noop(payload))

    def test_trusted_noop_rejects_untrusted_empty_pr(self) -> None:
        payload = {
            "body": "No changes needed.",
            "changed_files": 0,
            "additions": 0,
            "deletions": 0,
            "merged_at": None,
        }
        self.assertFalse(pull_request_is_trusted_noop(payload))

    def test_trusted_noop_rejects_any_real_diff(self) -> None:
        base = {
            "body": "PR created automatically by Jules for task [123]",
            "changed_files": 0,
            "additions": 0,
            "deletions": 0,
            "merged_at": None,
        }
        for field in ("changed_files", "additions", "deletions"):
            payload = dict(base)
            payload[field] = 1
            self.assertFalse(pull_request_is_trusted_noop(payload))

    def test_trusted_noop_rejects_merged_or_incomplete_pr_payload(self) -> None:
        base = {
            "body": "PR created automatically by Jules for task [123]",
            "changed_files": 0,
            "additions": 0,
            "deletions": 0,
            "merged_at": None,
        }
        merged = dict(base, merged_at="2026-10-10T00:00:00Z")
        self.assertFalse(pull_request_is_trusted_noop(merged))

        missing_counter = dict(base)
        del missing_counter["changed_files"]
        self.assertFalse(pull_request_is_trusted_noop(missing_counter))

        bool_counter = dict(base, changed_files=False)
        self.assertFalse(pull_request_is_trusted_noop(bool_counter))

    def test_receipt_binding_detects_idempotent_pr_created_receipt(self) -> None:
        payload = RemoteExecutionReceipt(
            task_id="v12ext-001",
            target_repository="M-Osugi1230/one-minute-thought-experiments",
            pull_request_url=(
                "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
            ),
            recorded_at="2026-09-29T00:00:00+00:00",
        ).to_dict()
        self.assertTrue(
            receipt_binds_pull_request(
                payload,
                task_id="v12ext-001",
                target_repository="M-Osugi1230/one-minute-thought-experiments",
                pull_request_url=(
                    "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
                ),
            )
        )
        self.assertFalse(
            receipt_binds_pull_request(
                payload,
                task_id="v12ext-002",
                target_repository="M-Osugi1230/one-minute-thought-experiments",
                pull_request_url=(
                    "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
                ),
            )
        )
        merged = dict(payload)
        merged["status"] = "MERGED"
        self.assertFalse(
            receipt_binds_pull_request(
                merged,
                task_id="v12ext-001",
                target_repository="M-Osugi1230/one-minute-thought-experiments",
                pull_request_url=(
                    "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
                ),
            )
        )

    def test_receipt_round_trip_and_repository_binding(self) -> None:
        receipt = RemoteExecutionReceipt(
            task_id="v12ext-001",
            target_repository="M-Osugi1230/one-minute-thought-experiments",
            pull_request_url=(
                "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
            ),
            recorded_at="2026-09-29T00:00:00+00:00",
        )
        self.assertEqual(
            RemoteExecutionReceipt.from_dict(receipt.to_dict()),
            receipt,
        )
        self.assertEqual(receipt.pull_request_number, 7)

        payload = receipt.to_dict()
        payload["target_repository"] = "M-Osugi1230/autonomous-development-engine"
        with self.assertRaisesRegex(ValueError, "does not match"):
            RemoteExecutionReceipt.from_dict(payload)


if __name__ == "__main__":
    unittest.main()
