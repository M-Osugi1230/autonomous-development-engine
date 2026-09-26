from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ade import (
    CheckpointState,
    CheckpointStore,
    DecisionPriority,
    DecisionRecord,
    DecisionRequest,
    DecisionStore,
    FailureKind,
    TaskCheckpoint,
    build_mission_control_snapshot,
    render_mission_control,
)
from build_mission_control import build_artifacts


SECRET_LIKE_PROVIDER_VALUE = "ghp_123456789012345678901234567890123456"
RAW_DECISION_CONTEXT = "private-context-must-not-render"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_fixture(root: Path) -> None:
    autodev = root / ".autodev"
    runtime = autodev / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)

    _write_json(
        autodev / "state.json",
        {
            "schema_version": 1,
            "project_id": "mission-control-probe",
            "status": "HUMAN_WAIT",
            "iteration": 4,
            "current_task_id": "task-5",
            "completed_task_ids": ["task-1", "task-2", "task-3"],
            "failed_task_ids": ["task-4"],
            "provider": "jules",
            "updated_at": "2026-09-26T01:00:00+00:00",
            "metadata": {
                "phase": "phase8-mission-control",
                "milestone": "read-only-artifact-proof",
                "queue_exhausted": False,
            },
        },
    )
    _write_json(
        autodev / "task-queue.json",
        {
            "schema_version": 1,
            "tasks": [
                {"task_id": "task-6"},
                {"task_id": "task-7"},
            ],
        },
    )
    _write_json(
        autodev / "failures.json",
        {
            "schema_version": 1,
            "failures": [{"task_id": "task-4", "kind": "test"}],
        },
    )
    _write_json(
        autodev / "metrics.json",
        {
            "schema_version": 1,
            "cycles_started": 2,
            "cycles_completed": 1,
            "repair_attempts": 1,
            "human_interrupts": 1,
            "quota_pauses": 1,
        },
    )

    CheckpointStore(runtime / "checkpoint.json").save(
        TaskCheckpoint(
            task_id="task-5",
            state=CheckpointState.HUMAN_WAIT,
            attempt=1,
            replan_count=0,
            provider_session_id=SECRET_LIKE_PROVIDER_VALUE,
            last_failure_kind=FailureKind.HUMAN_INPUT,
            last_error="human input required",
        )
    )

    DecisionStore(autodev / "decisions.json").save(
        [
            DecisionRecord(
                request=DecisionRequest(
                    decision_id="decision-phase8-proof",
                    question="Approve the irreversible production migration?",
                    options=("approve", "reject"),
                    priority=DecisionPriority.P0,
                    blocking_task_id="task-5",
                    context={"private": RAW_DECISION_CONTEXT},
                )
            )
        ]
    )


def run_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "repo"
        output = Path(temp_dir) / "artifact" / "mission-control"
        _build_fixture(root)

        snapshot = build_mission_control_snapshot(root)
        html = render_mission_control(snapshot)

        html_path, snapshot_path = build_artifacts(
            repo_root=root,
            output_dir=output,
        )
        reloaded = json.loads(snapshot_path.read_text(encoding="utf-8"))
        artifact_html = html_path.read_text(encoding="utf-8")

        if snapshot.project_id != "mission-control-probe":
            raise AssertionError("project id mismatch")
        if snapshot.completed_tasks != 3:
            raise AssertionError("completed task count mismatch")
        if snapshot.failed_tasks != 1:
            raise AssertionError("failed task count mismatch")
        if snapshot.queue_depth != 2:
            raise AssertionError("queue depth mismatch")
        if len(snapshot.open_decisions) != 1:
            raise AssertionError("expected exactly one open decision")

        decision = snapshot.open_decisions[0]
        if decision.decision_id != "decision-phase8-proof":
            raise AssertionError("open decision id mismatch")
        if decision.question != "Approve the irreversible production migration?":
            raise AssertionError("open decision question mismatch")

        expected_warning = "telemetry metrics lag project iteration"
        if expected_warning not in snapshot.warnings:
            raise AssertionError("stale telemetry warning is missing")

        serialized_snapshot = json.dumps(
            snapshot.to_dict(),
            sort_keys=True,
            ensure_ascii=False,
        )
        combined = "\n".join(
            [
                serialized_snapshot,
                html,
                snapshot_path.read_text(encoding="utf-8"),
                artifact_html,
            ]
        )
        for forbidden in (SECRET_LIKE_PROVIDER_VALUE, RAW_DECISION_CONTEXT):
            if forbidden in combined:
                raise AssertionError(f"sensitive fixture value leaked: {forbidden}")

        lowered = artifact_html.lower()
        for forbidden in ("<script", "http://", "https://", "@import", " src="):
            if forbidden in lowered:
                raise AssertionError(f"unsafe HTML token found: {forbidden}")

        if reloaded.get("project_id") != "mission-control-probe":
            raise AssertionError("snapshot.json reload project id mismatch")
        if reloaded.get("queue_depth") != 2:
            raise AssertionError("snapshot.json reload queue depth mismatch")
        open_decisions = reloaded.get("open_decisions")
        if not isinstance(open_decisions, list) or len(open_decisions) != 1:
            raise AssertionError("snapshot.json open decision mismatch")

        return {
            "ok": True,
            "project_id": snapshot.project_id,
            "completed_tasks": snapshot.completed_tasks,
            "failed_tasks": snapshot.failed_tasks,
            "queue_depth": snapshot.queue_depth,
            "open_decision_id": decision.decision_id,
            "warning_count": len(snapshot.warnings),
            "artifact_files": sorted([html_path.name, snapshot_path.name]),
        }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
