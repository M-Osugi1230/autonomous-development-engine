from __future__ import annotations

import unittest

from ade.cycle import CycleFailed, CycleTask, HumanInputRequired, run_cycle


class _Provider:
    def __init__(self, states):
        self.states = iter(states)
        self.created = None

    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        self.created = kwargs
        return {"id": "abc", "url": "https://example.test/session/abc"}

    def get_session(self, session_id):
        state = next(self.states)
        payload = {"id": session_id, "state": state}
        if state == "COMPLETED":
            payload["outputs"] = [
                {"pullRequest": {"url": "https://github.com/example/demo/pull/1"}}
            ]
        return payload

    def list_activities(self, session_id):
        return []

    def send_message(self, session_id, prompt):
        return None

    def approve_plan(self, session_id):
        return None


class CycleTests(unittest.TestCase):
    def test_completed_cycle_returns_pr(self):
        provider = _Provider(["QUEUED", "IN_PROGRESS", "COMPLETED"])
        task = CycleTask(
            task_id="t1",
            title="Demo",
            prompt="Do the work",
            poll_interval_seconds=5,
            timeout_seconds=60,
        )

        ticks = iter([0, 0, 1, 2, 3, 4])
        result = run_cycle(
            provider,
            task=task,
            source_name="sources/github/example/demo",
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
        )

        self.assertEqual(result.state, "COMPLETED")
        self.assertEqual(
            result.pull_request_url,
            "https://github.com/example/demo/pull/1",
        )
        self.assertTrue(provider.created["auto_create_pr"])

    def test_failed_cycle_raises(self):
        provider = _Provider(["FAILED"])
        task = CycleTask(
            task_id="t1",
            title="Demo",
            prompt="Do the work",
            poll_interval_seconds=5,
            timeout_seconds=60,
        )
        with self.assertRaises(CycleFailed):
            run_cycle(
                provider,
                task=task,
                source_name="sources/github/example/demo",
                sleeper=lambda _: None,
                clock=lambda: 0,
            )

    def test_human_wait_is_explicit(self):
        provider = _Provider(["AWAITING_USER_FEEDBACK"])
        task = CycleTask(
            task_id="t1",
            title="Demo",
            prompt="Do the work",
            poll_interval_seconds=5,
            timeout_seconds=60,
        )
        with self.assertRaises(HumanInputRequired):
            run_cycle(
                provider,
                task=task,
                source_name="sources/github/example/demo",
                sleeper=lambda _: None,
                clock=lambda: 0,
            )


if __name__ == "__main__":
    unittest.main()
