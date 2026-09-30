from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_store import DevelopmentMemoryStore

SCRIPT = Path(".github/trusted/v1_6_backlog_successor.py")
spec = importlib.util.spec_from_file_location("v1_6_backlog_successor_probe_module", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def main() -> int:
    record = DevelopmentMemoryRecord(
        memory_id="mem-" + "1" * 24,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=REPO,
        source_sha=SHA,
        statement=(
            "Trusted runtime verification completed with every required probe "
            "passing against the exact source SHA."
        ),
        task_id="v15mem2-001",
        evidence_paths=(
            ".autodev/runtime-verification/v15mem2-001/contract.json",
            ".autodev/runtime-verification/v15mem2-001/receipt.json",
            ".autodev/runtime-verification/v15mem2-001/report.json",
        ),
        evidence_fingerprints=("1" * 64, "2" * 64, "3" * 64),
        tags=("feedback", "runtime", "verified"),
    )
    store = DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=(record,))
    )
    state = {
        "schema_version": 1,
        "project_id": "ade-proof",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": ["v15mem2-001"],
        "failed_task_ids": [],
        "metadata": {
            "v1_5_graduated": True,
            "phase": "v1.5-development-memory",
        },
    }

    activation = module.build_activation(
        state_payload=state,
        store_payload=store.canonical_dict(),
    )
    assert activation["source_memory_id"] == record.memory_id
    assert activation["source_memory_fingerprint"] == record.fingerprint()
    assert activation["selection"]["selected_candidate_id"] == activation["candidate_id"]
    assert activation["planning_goal"]["allowed_path_prefixes"] == ["tests"]
    assert activation["planning_goal"]["min_tasks"] == 1
    assert activation["planning_goal"]["max_tasks"] == 1
    assert activation["handoff"]["execution_authority"] is False
    assert activation["handoff"]["accepted_plan_authority"] is False
    assert activation["handoff"]["auto_dispatch"] is False

    blocked = False
    state["metadata"]["v1_5_graduated"] = False
    try:
        module.build_activation(
            state_payload=state,
            store_payload=store.canonical_dict(),
        )
    except ValueError:
        blocked = True
    assert blocked

    print(
        json.dumps(
            {
                "ok": True,
                "requires_v1_5_graduation": True,
                "requires_exact_proof002_verified_memory": True,
                "source_store_snapshot_bound": True,
                "single_candidate": True,
                "tests_only_planning_goal": True,
                "max_tasks": 1,
                "execution_authority": False,
                "accepted_plan_authority": False,
                "auto_dispatch": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
