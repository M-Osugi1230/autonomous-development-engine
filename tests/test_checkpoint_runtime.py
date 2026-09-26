import tempfile
import unittest
from pathlib import Path

from ade import (
    CheckpointState,
    CheckpointStore,
    CheckpointedCycleExecution,
    CycleFailed,
    CycleResult,
    CycleSession,
    CycleTask,
    CycleTimedOut,
    FailureKind,
    HumanInputRequired,
    RepairDisposition,
    RepairPolicy,
    TaskCheckpoint,
    run_checkpointed_cycle,
)
from ade.providers.base import ProviderQuotaError


class DummyProvider:
    pass


class TestCheckpointRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_dir.name) / "checkpoint.json"
        self.store = CheckpointStore(self.store_path)
        self.task = CycleTask(
            task_id="task-100",
            title="Test Task",
            prompt="Do something testable",
        )
        self.provider = DummyProvider()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_crash_resume_with_preseeded_running_checkpoint(self) -> None:
        preseeded_chk = TaskCheckpoint(
            task_id="task-100",
            state=CheckpointState.RUNNING,
            attempt=1,
            replan_count=0,
            provider_session_id="sess-preseeded",
        )
        self.store.save(preseeded_chk)

        start_called = []

        def mock_start(provider, *, task, source_name):
            start_called.append(True)
            return CycleSession(task_id=task.task_id, session_id="sess-new")

        def mock_monitor(provider, *, task, session):
            self.assertEqual(session.session_id, "sess-preseeded")
            return CycleResult(
                task_id=task.task_id,
                session_id=session.session_id,
                session_url=None,
                state="COMPLETED",
                pull_request_url="https://github.com/org/repo/pull/1",
            )

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            existing_checkpoint=preseeded_chk,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertFalse(start_called)
        self.assertIsNotNone(execution.result)
        self.assertEqual(execution.result.session_id, "sess-preseeded")

        saved_chk = self.store.load()
        self.assertEqual(saved_chk.state, CheckpointState.COMPLETED)
        self.assertEqual(saved_chk.provider_session_id, "sess-preseeded")
        self.assertEqual(saved_chk.attempt, 1)

    def test_fresh_run_saves_running_before_monitor(self) -> None:
        events = []

        def mock_start(provider, *, task, source_name):
            events.append("start")
            return CycleSession(task_id=task.task_id, session_id="sess-fresh")

        def mock_monitor(provider, *, task, session):
            events.append("monitor")
            chk_at_monitor = self.store.load()
            self.assertEqual(chk_at_monitor.state, CheckpointState.RUNNING)
            self.assertEqual(chk_at_monitor.provider_session_id, "sess-fresh")
            return CycleResult(
                task_id=task.task_id,
                session_id=session.session_id,
                session_url=None,
                state="COMPLETED",
                pull_request_url=None,
            )

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertEqual(events, ["start", "monitor"])
        self.assertIsNotNone(execution.result)
        saved_chk = self.store.load()
        self.assertEqual(saved_chk.state, CheckpointState.COMPLETED)

    def test_completion_saves_completed(self) -> None:
        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id="sess-comp")

        def mock_monitor(provider, *, task, session):
            return CycleResult(
                task_id=task.task_id,
                session_id=session.session_id,
                session_url="https://provider/sess-comp",
                state="COMPLETED",
                pull_request_url="https://github.com/org/repo/pull/42",
            )

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        saved = self.store.load()
        self.assertEqual(saved.state, CheckpointState.COMPLETED)
        self.assertEqual(saved.task_id, "task-100")
        self.assertEqual(saved.provider_session_id, "sess-comp")
        self.assertIsNone(saved.last_failure_kind)
        self.assertIsNone(saved.last_error)

    def test_quota_pause_persists(self) -> None:
        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id="sess-quota")

        def mock_monitor(provider, *, task, session):
            raise ProviderQuotaError("Quota limit reached for provider gh_app")

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertIsNone(execution.result)
        self.assertIsNotNone(execution.checkpoint)
        self.assertEqual(execution.checkpoint.state, CheckpointState.PAUSED_QUOTA)
        self.assertEqual(execution.checkpoint.last_failure_kind, FailureKind.PROVIDER_QUOTA)

        saved = self.store.load()
        self.assertEqual(saved.state, CheckpointState.PAUSED_QUOTA)
        self.assertIn("Quota limit reached", saved.last_error)

    def test_human_wait_persists(self) -> None:
        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id="sess-human")

        def mock_monitor(provider, *, task, session):
            raise HumanInputRequired("User input required to resolve ambiguity")

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertIsNone(execution.result)
        self.assertEqual(execution.checkpoint.state, CheckpointState.HUMAN_WAIT)
        self.assertEqual(execution.checkpoint.last_failure_kind, FailureKind.HUMAN_INPUT)

        saved = self.store.load()
        self.assertEqual(saved.state, CheckpointState.HUMAN_WAIT)

    def test_bounded_retry_and_counters_persisted(self) -> None:
        monitor_attempts = 0
        persisted_states = []

        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id=f"sess-{monitor_attempts}")

        def mock_monitor(provider, *, task, session):
            nonlocal monitor_attempts
            monitor_attempts += 1
            persisted_states.append(self.store.load())
            if monitor_attempts == 1:
                raise CycleTimedOut("Timeout on attempt 0")
            if monitor_attempts == 2:
                raise CycleTimedOut("Timeout on attempt 1")
            return CycleResult(
                task_id=task.task_id,
                session_id=session.session_id,
                session_url=None,
                state="COMPLETED",
                pull_request_url=None,
            )

        policy = RepairPolicy(max_retries=2, max_replans=0)

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            policy=policy,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertEqual(monitor_attempts, 3)
        self.assertIsNotNone(execution.result)
        self.assertEqual(len(execution.history), 2)
        self.assertEqual(execution.history[0].disposition, RepairDisposition.RETRY)
        self.assertEqual(execution.history[0].next_attempt, 1)
        self.assertEqual(execution.history[1].disposition, RepairDisposition.RETRY)
        self.assertEqual(execution.history[1].next_attempt, 2)

        saved = self.store.load()
        self.assertEqual(saved.state, CheckpointState.COMPLETED)
        self.assertEqual(saved.attempt, 2)

    def test_bounded_retry_exceeded_persists_replan_or_fail(self) -> None:
        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id="sess-fail")

        def mock_monitor(provider, *, task, session):
            raise CycleFailed("Session failed permanently")

        policy = RepairPolicy(max_retries=1, max_replans=0)

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            policy=policy,
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        self.assertEqual(len(execution.history), 2)
        self.assertEqual(execution.history[0].disposition, RepairDisposition.RETRY)
        self.assertEqual(execution.history[1].disposition, RepairDisposition.FAIL)

        saved = self.store.load()
        self.assertEqual(saved.state, CheckpointState.FAILED)
        self.assertEqual(saved.attempt, 1)

    def test_mismatched_task_checkpoint_rejected(self) -> None:
        mismatched_chk = TaskCheckpoint(
            task_id="task-OTHER",
            state=CheckpointState.RUNNING,
            attempt=0,
            replan_count=0,
            provider_session_id="sess-other",
        )

        with self.assertRaises(ValueError) as ctx:
            run_checkpointed_cycle(
                self.provider,
                task=self.task,
                source_name="github",
                store=self.store,
                existing_checkpoint=mismatched_chk,
            )
        self.assertIn("task_id", str(ctx.exception))

    def test_terminal_and_human_wait_checkpoint_not_resumed(self) -> None:
        for state in (CheckpointState.HUMAN_WAIT, CheckpointState.FAILED, CheckpointState.COMPLETED):
            chk = TaskCheckpoint(
                task_id="task-100",
                state=state,
                attempt=0,
                replan_count=0,
            )
            with self.assertRaises(ValueError) as ctx:
                run_checkpointed_cycle(
                    self.provider,
                    task=self.task,
                    source_name="github",
                    store=self.store,
                    existing_checkpoint=chk,
                )
            self.assertIn("Cannot resume", str(ctx.exception))

    def test_secrets_and_tracebacks_not_in_checkpoint(self) -> None:
        def mock_start(provider, *, task, source_name):
            return CycleSession(task_id=task.task_id, session_id="sess-secret")

        def mock_monitor(provider, *, task, session):
            raise CycleFailed("Cycle failed with token ghp_123456789012345678901234567890123456")

        execution = run_checkpointed_cycle(
            self.provider,
            task=self.task,
            source_name="github",
            store=self.store,
            policy=RepairPolicy(max_retries=0, max_replans=0),
            start_fn=mock_start,
            monitor_fn=mock_monitor,
        )

        saved = self.store.load()
        self.assertNotIn("ghp_", saved.last_error or "")
        self.assertNotIn("Traceback", saved.last_error or "")


if __name__ == "__main__":
    unittest.main()
