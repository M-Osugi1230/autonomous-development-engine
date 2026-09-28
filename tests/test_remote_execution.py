from __future__ import annotations

import unittest

from ade.remote_execution import (
    RemoteExecutionReceipt,
    execution_target_from_state,
    parse_pull_request_url,
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
