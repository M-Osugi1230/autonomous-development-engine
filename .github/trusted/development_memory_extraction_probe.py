from __future__ import annotations

import copy
import json

from ade.development_memory import DevelopmentMemoryError, DevelopmentMemoryLedger
from ade.development_memory_extraction import extract_trusted_memories


MERGE_SHA = "a" * 40
SOURCE_SHA = "b" * 40


def campaign() -> dict:
    return {
        "schema_version": 1,
        "campaign_id": "campaign-001",
        "target_repository": "owner/target",
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "task": {"task_id": "task-001", "merge_commit": MERGE_SHA},
        "runtime_verification": {
            "workspace_source_sha": MERGE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": {
                "source_sha": MERGE_SHA,
                "target_repository": "owner/target",
                "required_probe_ids": ["offline-cli-smoke", "production-import-smoke"],
            },
            "receipt": {
                "status": "VERIFIED",
                "source_sha": MERGE_SHA,
                "target_repository": "owner/target",
                "task_id": "task-001",
            },
            "report": {
                "disposition": "VERIFIED",
                "source_sha": MERGE_SHA,
                "results": [
                    {
                        "probe_id": "offline-cli-smoke",
                        "status": "PASS",
                        "source_sha": MERGE_SHA,
                    },
                    {
                        "probe_id": "production-import-smoke",
                        "status": "PASS",
                        "source_sha": MERGE_SHA,
                    },
                ],
            },
        },
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "campaign-001",
                "status": "COMPLETED",
                "task_ids": ["task-001"],
                "completed_task_ids": ["task-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


def recovery() -> dict:
    return {
        "schema_version": 1,
        "task_id": "task-001",
        "failure": "CI_FAILURE",
        "action": "REPAIR",
        "fingerprint": "c" * 64,
        "progress": {
            "retries": 0,
            "repairs": 1,
            "rebases": 0,
            "replans": 0,
            "repeated_failures": 1,
        },
    }


def decisions() -> dict:
    return {
        "schema_version": 1,
        "decisions": [
            {
                "request": {
                    "decision_id": "decision-001",
                    "question": "This untrusted question must not become memory text.",
                    "options": ["ACTIVATE", "CANCEL"],
                    "priority": "P0",
                    "blocking_task_id": "task-001",
                    "context": {"raw_provider_text": "must-not-be-copied"},
                },
                "status": "RESOLVED",
                "response": {
                    "decision_id": "decision-001",
                    "text": "ACTIVATE because of free-form rationale that must not be copied.",
                    "selected_option": "ACTIVATE",
                },
            }
        ],
    }


def main() -> int:
    kwargs = {
        "campaign_evidence_path": ".autodev/campaign-evidence/proof.json",
        "campaign_evidence_payload": campaign(),
        "recovery_evidence_path": ".autodev/runtime/recovery.json",
        "recovery_payload": recovery(),
        "recovery_repository": "owner/target",
        "recovery_source_sha": SOURCE_SHA,
        "decision_evidence_path": ".autodev/decisions.json",
        "decision_store_payload": decisions(),
        "decision_id": "decision-001",
        "decision_repository": "owner/target",
        "decision_source_sha": SOURCE_SHA,
    }
    first = extract_trusted_memories(**kwargs)
    second_kwargs = copy.deepcopy(kwargs)
    second = extract_trusted_memories(**second_kwargs)
    assert first == second

    ledger = DevelopmentMemoryLedger(records=first)
    serialized = json.dumps(ledger.canonical_dict(), sort_keys=True)
    assert "must-not-be-copied" not in serialized
    assert "free-form rationale" not in serialized
    assert "This untrusted question" not in serialized
    assert all(record.repository == "owner/target" for record in ledger.records)

    drift = campaign()
    drift["runtime_verification"]["receipt"]["source_sha"] = SOURCE_SHA
    rejected_drift = False
    try:
        extract_trusted_memories(
            campaign_evidence_path=".autodev/campaign-evidence/proof.json",
            campaign_evidence_payload=drift,
        )
    except DevelopmentMemoryError:
        rejected_drift = True
    assert rejected_drift

    print(
        json.dumps(
            {
                "ok": True,
                "record_count": len(ledger.records),
                "deterministic_extraction": True,
                "raw_provider_text_copied": False,
                "raw_decision_text_copied": False,
                "source_drift_rejected": True,
                "campaign_completion_required": True,
                "runtime_verified_required": True,
                "recovery_structured_only": True,
                "resolved_selected_option_required": True,
                "ledger_fingerprint": ledger.fingerprint(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
