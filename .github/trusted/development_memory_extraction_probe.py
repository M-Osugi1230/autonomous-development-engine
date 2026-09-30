from __future__ import annotations

import json
from pathlib import Path

from ade.development_memory import DevelopmentMemoryLedger, build_planner_memory_context
from ade.development_memory_extraction import (
    extract_recovery_memory,
    extract_resolved_decision_memory,
    extract_runtime_verification_memory,
    extract_verified_campaign_memory,
)


ROOT = Path(".")
PROOF3_PATH = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json"
PROOF2_PATH = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-002-superseded.json"
RECOVERY_PATH = ".autodev/runtime/recovery.json"
DECISIONS_PATH = ".autodev/decisions.json"


def _load(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> int:
    proof3 = _load(PROOF3_PATH)
    proof2 = _load(PROOF2_PATH)
    recovery = _load(RECOVERY_PATH)
    decisions = _load(DECISIONS_PATH)

    campaign_memory = extract_verified_campaign_memory(
        proof3,
        evidence_path=PROOF3_PATH,
    )
    runtime_memory = extract_runtime_verification_memory(
        proof3,
        evidence_path=PROOF3_PATH,
    )

    proof2_external = proof2["external_execution"]
    recovery_memory = extract_recovery_memory(
        recovery,
        evidence_path=RECOVERY_PATH,
        repository=proof2["target_repository"],
        source_sha=proof2_external["merge_commit"],
    )

    resolved = [
        item
        for item in decisions["decisions"]
        if item.get("status") == "RESOLVED"
    ]
    if not resolved:
        raise RuntimeError("trusted decision ledger has no resolved decision")
    decision = resolved[0]
    context = decision["request"]["context"]
    decision_memory = extract_resolved_decision_memory(
        decision,
        evidence_path=DECISIONS_PATH,
        repository=context["target_repository"],
        source_sha=context["baseline_sha"],
    )

    ledger = DevelopmentMemoryLedger(
        records=(
            campaign_memory,
            runtime_memory,
            recovery_memory,
            decision_memory,
        )
    )
    planner_context = build_planner_memory_context(
        ledger,
        repository="M-Osugi1230/one-minute-thought-experiments",
        max_records=10,
        max_chars=6000,
    )

    statements = [record.statement for record in ledger.records]
    serialized = planner_context.serialized.casefold()
    forbidden = (
        "ignore all constraints",
        "provider_free_text",
        "raw_provider_text",
        "github_pat_",
        "ghp_",
        "bearer ",
        '"command"',
        '"headers"',
    )
    if any(value in serialized for value in forbidden):
        raise RuntimeError("trusted extracted memory leaked forbidden raw content")

    result = {
        "ok": True,
        "schema_version": 1,
        "record_count": len(ledger.records),
        "kinds": sorted(record.kind.value for record in ledger.records),
        "campaign_memory_id": campaign_memory.memory_id,
        "runtime_memory_id": runtime_memory.memory_id,
        "recovery_memory_id": recovery_memory.memory_id,
        "decision_memory_id": decision_memory.memory_id,
        "ledger_fingerprint": ledger.fingerprint(),
        "planner_context_fingerprint": planner_context.fingerprint,
        "fixed_controller_statements": len(statements) == 4,
        "raw_provider_text_copied": False,
        "resolved_human_decision_required": True,
        "verified_runtime_required": True,
        "clean_campaign_provenance_required": True,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
