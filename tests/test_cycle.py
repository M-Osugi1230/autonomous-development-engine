from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from ade.cycle import (
    CycleFailed,
    CyclePaused,
    CycleResult,
    CycleSession,
    CycleTask,
    CycleTimedOut,
    HumanInputRequired,
    monitor_cycle_session,
    run_cycle,
    start_cycle_session,
)


class _Provider:
    def __init__(self, states):
        self.states = iter(states)
        self.created = None
        self.create_calls = 0

    def list_sources(self):
        return []

    def create_session(self, **kwargs):
        self.create_calls += 1
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


class CycleSessionTests(unittest.TestCase):
    def test_cycle_session_creation_and_immutability(self):
        session = CycleSession(
            task_id="t1",
            session_id="s1",
            session_url="https://example.test/s1",
        )
        self.assertEqual(session.task_id, "t1")
        self.assertEqual(session.session_id, "s1")
        self.assertEqual(session.session_url, "https://example.test/s1")

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            session.session_id = "s2"  # type: ignore[misc]

    def test_cycle_session_validation(self):
        with self.assertRaises(ValueError):
            CycleSession(task_id="", session_id="s1")
        with self.assertRaises(ValueError):
            CycleSession(task_id="t1", session_id="   ")
        with self.assertRaises(ValueError):
            CycleSession(task_id="t1", session_id="s1", session_url="")

        valid_none_url = CycleSession(task_id="t1", session_id="s1", session_url=None)
        self.assertIsNone(valid_none_url.session_url)

    def test_cycle_session_dict_roundtrip(self):
        session = CycleSession(
            task_id="t1",
            session_id="s1",
            session_url="https://example.test/s1",
        )
        payload = session.to_dict()
        reconstructed = CycleSession.from_dict(payload)
        self.assertEqual(session, reconstructed)


class CycleTests(unittest.TestCase):
    def test_start_cycle_session_creates_exactly_one_session(self):
        provider = _Provider([])
        task = CycleTask(
            task_id="t1",
            title="Demo",
            prompt="Do the work",
        )
        session = start_cycle_session(
            provider,
            task=task,
            source_name="sources/github/example/demo",
        )
        self.assertEqual(provider.create_calls, 1)
        self.assertEqual(session.task_id, "t1")
        self.assertEqual(session.session_id, "abc")
        self.assertEqual(session.session_url, "https://example.test/session/abc")

    def test_start_cycle_session_validates_source_name(self):
        provider = _Provider([])
        task = CycleTask(task_id="t1", title="Demo", prompt="Do work")
        with self.assertRaises(ValueError):
            start_cycle_session(provider, task=task, source_name="")

    def test_monitor_cycle_session_resumes_without_calling_create_session(self):
        provider = _Provider(["QUEUED", "COMPLETED"])
        task = CycleTask(
            task_id="t1",
            title="Demo",
            prompt="Do the work",
            poll_interval_seconds=5,
            timeout_seconds=60,
        )
        session = CycleSession(
            task_id="t1",
            session_id="abc",
            session_url="https://example.test/session/abc",
        )

        ticks = iter([0, 0, 1])
        result = monitor_cycle_session(
            provider,
            task=task,
            session=session,
            sleeper=lambda _: None,
            clock=lambda: next(ticks),
        )

        self.assertEqual(provider.create_calls, 0)
        self.assertEqual(result.task_id, "t1")
        self.assertEqual(result.session_id, "abc")
        self.assertEqual(result.session_url, "https://example.test/session/abc")
        self.assertEqual(result.state, "COMPLETED")
        self.assertEqual(result.pull_request_url, "https://github.com/example/demo/pull/1")

    def test_monitor_cycle_session_rejects_task_mismatch(self):
        provider = _Provider([])
        task = CycleTask(task_id="t1", title="Demo", prompt="Work")
        session = CycleSession(task_id="t2", session_id="abc")
        with self.assertRaises(ValueError):
            monitor_cycle_session(provider, task=task, session=session)

    def test_monitor_cycle_session_states(self):
        task = CycleTask(task_id="t1", title="Demo", prompt="Work", poll_interval_seconds=5, timeout_seconds=60)
        session = CycleSession(task_id="t1", session_id="abc")

        # FAILED state
        provider_failed = _Provider(["FAILED"])
        with self.assertRaises(CycleFailed):
            monitor_cycle_session(provider_failed, task=task, session=session, sleeper=lambda _: None, clock=lambda: 0)
        self.assertEqual(provider_failed.create_calls, 0)

        # AWAITING_USER_FEEDBACK state
        provider_feedback = _Provider(["AWAITING_USER_FEEDBACK"])
        with self.assertRaises(HumanInputRequired):
            monitor_cycle_session(provider_feedback, task=task, session=session, sleeper=lambda _: None, clock=lambda: 0)
        self.assertEqual(provider_feedback.create_calls, 0)

        # PAUSED state
        provider_paused = _Provider(["PAUSED"])
        with self.assertRaises(CyclePaused):
            monitor_cycle_session(provider_paused, task=task, session=session, sleeper=lambda _: None, clock=lambda: 0)
        self.assertEqual(provider_paused.create_calls, 0)

        # Timeout state
        provider_timeout = _Provider(["IN_PROGRESS"])
        ticks = iter([0, 65])
        with self.assertRaises(CycleTimedOut):
            monitor_cycle_session(provider_timeout, task=task, session=session, sleeper=lambda _: None, clock=lambda: next(ticks))
        self.assertEqual(provider_timeout.create_calls, 0)

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

        self.assertEqual(provider.create_calls, 1)
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
        self.assertEqual(provider.create_calls, 1)

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
        self.assertEqual(provider.create_calls, 1)


if __name__ == "__main__":
    unittest.main()
