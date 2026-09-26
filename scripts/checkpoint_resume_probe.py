from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ade import (
    CheckpointState,
    CheckpointStore,
    CycleTask,
    run_checkpointed_cycle,
)


class ProbeInterruption(BaseException):
    """Simulates process termination outside ADE's Exception repair boundary."""


class FakeProvider:
    def __init__(self) -> None:
        self.create_session_calls = 0
        self.get_session_calls = 0
        self.session_id = "probe-session-1"

    def create_session(
        self,
        *,
        prompt: str,
        source: str,
        starting_branch: str,
        title: str | None = None,
        auto_create_pr: bool = False,
        require_plan_approval: bool = False,
    ) -> dict[str, Any]:
        self.create_session_calls += 1
        return {
            "id": self.session_id,
            "url": f"https://example.invalid/sessions/{self.session_id}",
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        self.get_session_calls += 1
        if session_id != self.session_id:
            raise AssertionError(f"unexpected session id: {session_id}")
        return {
            "state": "COMPLETED",
            "outputs": [
                {
                    "pullRequest": {
                        "url": "https://example.invalid/pull/1",
                    }
                }
            ],
        }


def run_probe() -> dict[str, Any]:
    provider = FakeProvider()
    task = CycleTask(
        task_id="phase6-crash-restart-probe",
        title="Phase 6 crash restart probe",
        prompt="Exercise crash-safe checkpoint continuation.",
        timeout_seconds=60,
        poll_interval_seconds=5,
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = CheckpointStore(Path(temp_dir) / "checkpoint.json")
        observed_running: dict[str, Any] = {}

        def interrupt_after_checkpoint(provider_obj, *, task, session):
            checkpoint = store.load()
            if checkpoint.state is not CheckpointState.RUNNING:
                raise AssertionError("RUNNING checkpoint was not persisted before monitor")
            if checkpoint.provider_session_id != session.session_id:
                raise AssertionError("persisted session id does not match active session")
            observed_running.update(checkpoint.to_dict())
            raise ProbeInterruption("simulated process interruption")

        interrupted = False
        try:
            run_checkpointed_cycle(
                provider,
                task=task,
                source_name="probe-source",
                store=store,
                monitor_fn=interrupt_after_checkpoint,
            )
        except ProbeInterruption:
            interrupted = True

        if not interrupted:
            raise AssertionError("first invocation did not simulate interruption")

        running_checkpoint = store.load()
        if running_checkpoint.state is not CheckpointState.RUNNING:
            raise AssertionError("checkpoint was not RUNNING after interruption")
        if running_checkpoint.provider_session_id != provider.session_id:
            raise AssertionError("RUNNING checkpoint lost provider session id")
        if provider.create_session_calls != 1:
            raise AssertionError("first invocation must create exactly one provider session")

        resumed = run_checkpointed_cycle(
            provider,
            task=task,
            source_name="probe-source",
            store=store,
            existing_checkpoint=running_checkpoint,
        )

        final_checkpoint = store.load()
        if resumed.result is None:
            raise AssertionError("resumed execution did not produce a CycleResult")
        if resumed.result.state != "COMPLETED":
            raise AssertionError("resumed execution did not reach COMPLETED")
        if resumed.result.session_id != provider.session_id:
            raise AssertionError("resumed execution changed provider session id")
        if provider.create_session_calls != 1:
            raise AssertionError("resume created a duplicate provider session")
        if final_checkpoint.state is not CheckpointState.COMPLETED:
            raise AssertionError("final checkpoint is not COMPLETED")
        if final_checkpoint.provider_session_id != provider.session_id:
            raise AssertionError("final checkpoint lost provider session id")

        return {
            "ok": True,
            "create_session_calls": provider.create_session_calls,
            "get_session_calls": provider.get_session_calls,
            "intermediate_state": observed_running["state"],
            "final_state": final_checkpoint.state.value,
            "session_id": provider.session_id,
        }


def main() -> int:
    try:
        result = run_probe()
    except BaseException as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
