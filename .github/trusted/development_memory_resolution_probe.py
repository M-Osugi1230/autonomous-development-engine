from __future__ import annotations

import json
from pathlib import Path

from ade.development_memory import DevelopmentMemoryLedger, DevelopmentMemoryRecord, MemoryKind
from ade.development_memory_extraction import evidence_fingerprint, extract_trusted_memories
from ade.development_memory_resolution import (
    MemoryDisposition,
    MemorySupersessionRule,
    SupersessionReason,
    resolve_development_memory,
)


PROOF3_PATH = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json"
PROOF2_PATH = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-002-superseded.json"
RECOVERY_PATH = ".autodev/runtime/recovery.json"
DECISIONS_PATH = ".autodev/decisions.json"


def load(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    proof3 = load(PROOF3_PATH)
    proof2 = load(PROOF2_PATH)
    recovery = load(RECOVERY_PATH)
    decisions = load(DECISIONS_PATH)
    resolved = next(
        item for item in decisions["decisions"]
        if item.get("status") == "RESOLVED"
    )
    decision_context = resolved["request"]["context"]

    records = extract_trusted_memories(
        campaign_evidence_path=PROOF3_PATH,
        campaign_evidence_payload=proof3,
        recovery_evidence_path=RECOVERY_PATH,
        recovery_payload=recovery,
        recovery_repository=proof2["target_repository"],
        recovery_source_sha=proof2["external_execution"]["merge_commit"],
        decision_evidence_path=DECISIONS_PATH,
        decision_store_payload=decisions,
        decision_id=resolved["request"]["decision_id"],
        decision_repository=decision_context["target_repository"],
        decision_source_sha=decision_context["baseline_sha"],
    )
    current_sha = proof3["task"]["merge_commit"]
    repository = proof3["target_repository"]

    base = resolve_development_memory(
        DevelopmentMemoryLedger(records=records),
        current_source_shas={repository: current_sha},
    )
    base_counts = {
        disposition.value: sum(
            entry.disposition is disposition
            for entry in base.entries
        )
        for disposition in MemoryDisposition
    }
    assert base_counts["ACTIVE"] == 2
    assert base_counts["STALE"] == 2
    assert base_counts["CONFLICT"] == 0
    assert base_counts["SUPERSEDED"] == 0

    runtime = next(
        record for record in records
        if "runtime" in record.tags
    )
    conflict = DevelopmentMemoryRecord(
        memory_id="mem-conflicting-runtime-fact",
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=runtime.repository,
        source_sha=runtime.source_sha,
        statement="A competing current runtime fact exists for conflict testing.",
        campaign_id=runtime.campaign_id,
        task_id=runtime.task_id,
        evidence_paths=(PROOF3_PATH,),
        evidence_fingerprints=("f" * 64,),
        tags=("runtime", "verified"),
    )
    conflict_view = resolve_development_memory(
        DevelopmentMemoryLedger(records=(*records, conflict)),
        current_source_shas={repository: current_sha},
    )
    runtime_entries = [
        entry for entry in conflict_view.entries
        if entry.subject == f"runtime:{runtime.task_id}"
    ]
    assert len(runtime_entries) == 2
    assert all(
        entry.disposition is MemoryDisposition.CONFLICT
        for entry in runtime_entries
    )

    rule = MemorySupersessionRule(
        rule_id="proof003-runtime-correction",
        old_memory_id=conflict.memory_id,
        new_memory_id=runtime.memory_id,
        reason=SupersessionReason.CORRECTION,
        evidence_path=PROOF3_PATH,
        evidence_fingerprint=evidence_fingerprint(proof3),
    )
    resolved_view = resolve_development_memory(
        DevelopmentMemoryLedger(records=(*records, conflict)),
        current_source_shas={repository: current_sha},
        supersessions=(rule,),
    )
    resolved_entries = {
        entry.memory_id: entry
        for entry in resolved_view.entries
    }
    assert (
        resolved_entries[conflict.memory_id].disposition
        is MemoryDisposition.SUPERSEDED
    )
    assert resolved_entries[conflict.memory_id].superseded_by == runtime.memory_id
    assert (
        resolved_entries[runtime.memory_id].disposition
        is MemoryDisposition.ACTIVE
    )
    assert all(
        record.source_sha == current_sha
        for record in resolved_view.active_records
    )

    print(
        json.dumps(
            {
                "ok": True,
                "schema_version": 1,
                "real_extracted_record_count": len(records),
                "base_dispositions": base_counts,
                "same_subject_conflict_detected": True,
                "conflict_excluded_from_active": True,
                "evidence_backed_supersession_resolved": True,
                "stale_source_excluded_from_active": True,
                "active_memory_ids": [
                    record.memory_id
                    for record in resolved_view.active_records
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
