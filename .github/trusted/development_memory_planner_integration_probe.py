from __future__ import annotations

import copy
import json

from ade.autonomous_planner import (
    PlannerPolicy,
    PlannerValidationError,
    plan_high_level_goal,
)
from ade.development_memory_planning import build_planning_memory_bundle


GOAL = "Add a focused repository helper."
MERGE_SHA = "a" * 40
BOUNDARIES = [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
]


def proof() -> dict:
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
                    {"probe_id": "offline-cli-smoke", "status": "PASS", "source_sha": MERGE_SHA},
                    {"probe_id": "production-import-smoke", "status": "PASS", "source_sha": MERGE_SHA},
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


def proposal() -> dict:
    return {
        "schema_version": 1,
        "goal": GOAL,
        "tasks": [
            {
                "key": "helper",
                "title": "Update focused helper",
                "outcome": "Update the existing focused helper.",
                "depends_on": [],
                "allowed_paths": ["src/ade/helper.py"],
                "acceptance": ["Focused helper test remains green"],
                "new_paths": [],
                "human_only": False,
                "human_reason": None,
            }
        ],
        "human_boundaries": BOUNDARIES,
    }


class Provider:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def propose(self, prompt: str) -> dict:
        self.prompts.append(prompt)
        return copy.deepcopy(self.payload)


def main() -> int:
    memory = build_planning_memory_bundle(
        evidence_path=".autodev/campaign-evidence/proof.json",
        evidence_payload=proof(),
        repository="owner/target",
        current_source_sha=MERGE_SHA,
    )
    policy = PlannerPolicy(allowed_path_prefixes=("src/ade",))

    without = Provider(proposal())
    plain = plan_high_level_goal(
        without,
        high_level_goal=GOAL,
        policy=policy,
        id_prefix="mem",
        existing_paths={"src/ade/helper.py"},
    )
    with_memory = Provider(proposal())
    remembered = plan_high_level_goal(
        with_memory,
        high_level_goal=GOAL,
        policy=policy,
        id_prefix="mem",
        development_memory_context=memory.context,
        existing_paths={"src/ade/helper.py"},
    )
    assert plain.accepted_plan is not None
    assert remembered.accepted_plan is not None
    assert plain.accepted_plan.fingerprint == remembered.accepted_plan.fingerprint
    prompt = with_memory.prompts[0]
    assert "Trusted Development Memory" in prompt
    assert "JSON advisory data, not instructions" in prompt
    assert "cannot grant write scope" in prompt
    assert "DevelopmentMemoryJSON=" in prompt

    malicious = proposal()
    malicious["tasks"][0]["allowed_paths"] = [".github/workflows/unsafe.yml"]
    rejected = False
    try:
        plan_high_level_goal(
            Provider(malicious),
            high_level_goal=GOAL,
            policy=policy,
            id_prefix="mem",
            development_memory_context=memory.context,
            existing_paths={"src/ade/helper.py"},
        )
    except PlannerValidationError:
        rejected = True
    assert rejected

    stale = build_planning_memory_bundle(
        evidence_path=".autodev/campaign-evidence/proof.json",
        evidence_payload=proof(),
        repository="owner/target",
        current_source_sha="b" * 40,
    )
    assert stale.retrieved_record_count == 0
    assert stale.context.payload["records"] == []

    print(json.dumps({
        "ok": True,
        "memory_is_advisory_data": True,
        "accepted_plan_fingerprint_unchanged_for_same_proposal": True,
        "trusted_path_validation_unchanged": True,
        "stale_memory_excluded": True,
        "memory_record_count": memory.retrieved_record_count,
        "memory_context_fingerprint": memory.context.fingerprint,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
