from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ade import (
    DecisionKind,
    DecisionPriority,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    DecisionStore,
    HumanInterruptCoordinator,
    InterruptDisposition,
)


def run_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as temp_dir:
        store_path = Path(temp_dir) / "decisions.json"
        store = DecisionStore(store_path)
        coordinator = HumanInterruptCoordinator(store)

        routine = DecisionRequest(
            decision_id="routine-1",
            question="Apply the reversible formatting cleanup?",
            options=("apply", "skip"),
            priority=DecisionPriority.P3,
            blocking_task_id="phase7-probe",
        )
        routine_disposition = coordinator.request_decision(
            DecisionKind.ROUTINE_REVERSIBLE,
            routine,
        )
        if routine_disposition is not InterruptDisposition.PROCEED:
            raise AssertionError("routine reversible work did not PROCEED")
        if store.load():
            raise AssertionError("routine reversible work unexpectedly created a decision")

        destructive = DecisionRequest(
            decision_id="destructive-1",
            question="Perform the irreversible destructive operation?",
            options=("approve", "reject"),
            priority=DecisionPriority.P0,
            blocking_task_id="phase7-probe",
            context={"scope": "probe-resource"},
        )
        first_wait = coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            destructive,
        )
        if first_wait is not InterruptDisposition.HUMAN_WAIT:
            raise AssertionError("destructive work did not enter HUMAN_WAIT")

        open_records = store.list_open()
        if len(open_records) != 1:
            raise AssertionError("destructive request did not create exactly one OPEN decision")
        if open_records[0].status is not DecisionStatus.OPEN:
            raise AssertionError("queued decision is not OPEN")

        second_wait = coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            destructive,
        )
        if second_wait is not InterruptDisposition.HUMAN_WAIT:
            raise AssertionError("repeated destructive request did not remain HUMAN_WAIT")
        if len(store.load()) != 1:
            raise AssertionError("repeated request created a duplicate decision")

        response = DecisionResponse(
            decision_id=destructive.decision_id,
            text="Reject until the required backup and approval are verified.",
            selected_option="reject",
        )
        resolved = coordinator.resolve(destructive.decision_id, response)
        if resolved.status is not DecisionStatus.RESOLVED:
            raise AssertionError("human response did not resolve the decision")
        if resolved.response != response:
            raise AssertionError("resolved decision changed the human response")

        reloaded_store = DecisionStore(store_path)
        reloaded_records = reloaded_store.load()
        if len(reloaded_records) != 1:
            raise AssertionError("reloaded store did not preserve exactly one decision")
        if reloaded_records[0] != resolved:
            raise AssertionError("reloaded store changed the resolved decision")

        reloaded_coordinator = HumanInterruptCoordinator(reloaded_store)
        retrieved = reloaded_coordinator.get_resolved_response(destructive.decision_id)
        if retrieved != response:
            raise AssertionError("resolved response was not retrieved unchanged")
        if reloaded_store.list_open():
            raise AssertionError("resolved decision remained in the OPEN queue")

        return {
            "ok": True,
            "routine": routine_disposition.value,
            "destructive": first_wait.value,
            "records": len(reloaded_records),
            "final_status": reloaded_records[0].status.value,
            "selected_option": retrieved.selected_option if retrieved else None,
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
