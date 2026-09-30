from __future__ import annotations

import json

from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_resolution import (
    MemoryResolutionStatus,
    MemorySupersession,
    MemorySupersessionReason,
    resolve_development_memory,
)


CURRENT = "a" * 40
OLD = "b" * 40


def item(
    memory_id: str,
    kind: MemoryKind,
    source_sha: str,
    statement: str,
    tags: tuple[str, ...],
    fingerprint: str,
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=kind,
        repository="owner/repo",
        source_sha=source_sha,
        statement=statement,
        evidence_paths=(f".autodev/evidence/{memory_id}.json",),
        evidence_fingerprints=(fingerprint,),
        tags=tags,
        task_id="task-001",
    )


def main() -> int:
    stale = item(
        "memory-stale",
        MemoryKind.VERIFIED_OUTCOME,
        OLD,
        "Older runtime verification passed.",
        ("runtime", "verified"),
        "1" * 64,
    )
    old_rule = item(
        "memory-old-rule",
        MemoryKind.REMEDIATION,
        OLD,
        "Older recovery rule.",
        ("recovery", "rule"),
        "2" * 64,
    )
    new_rule = item(
        "memory-new-rule",
        MemoryKind.REMEDIATION,
        CURRENT,
        "New recovery rule.",
        ("recovery", "rule"),
        "3" * 64,
    )
    conflict_a = item(
        "memory-conflict-a",
        MemoryKind.VERIFIED_OUTCOME,
        CURRENT,
        "Runtime status is verified.",
        ("runtime", "status"),
        "4" * 64,
    )
    conflict_b = item(
        "memory-conflict-b",
        MemoryKind.VERIFIED_OUTCOME,
        CURRENT,
        "Runtime status is not verified.",
        ("runtime", "status"),
        "5" * 64,
    )
    historical = item(
        "memory-history",
        MemoryKind.FAILURE,
        OLD,
        "A prior runtime attempt failed closed.",
        ("runtime", "failure"),
        "6" * 64,
    )

    ledger = DevelopmentMemoryLedger(
        records=(
            stale,
            old_rule,
            new_rule,
            conflict_a,
            conflict_b,
            historical,
        )
    )
    resolution = resolve_development_memory(
        ledger,
        current_source_shas={"owner/repo": CURRENT},
        supersessions=(
            MemorySupersession(
                superseded_memory_id="memory-old-rule",
                successor_memory_id="memory-new-rule",
                reason=MemorySupersessionReason.CORRECTED,
            ),
        ),
    )
    statuses = {
        item.record.memory_id: item.status.value
        for item in resolution.records
    }
    assert statuses["memory-stale"] == MemoryResolutionStatus.STALE.value
    assert statuses["memory-old-rule"] == MemoryResolutionStatus.SUPERSEDED.value
    assert statuses["memory-new-rule"] == MemoryResolutionStatus.HISTORICAL.value
    assert statuses["memory-conflict-a"] == MemoryResolutionStatus.CONFLICTED.value
    assert statuses["memory-conflict-b"] == MemoryResolutionStatus.CONFLICTED.value
    assert statuses["memory-history"] == MemoryResolutionStatus.HISTORICAL.value

    eligible = {
        record.memory_id
        for record in resolution.eligible_ledger().records
    }
    assert eligible == {"memory-new-rule", "memory-history"}

    print(
        json.dumps(
            {
                "ok": True,
                "stale_excluded": True,
                "superseded_excluded": True,
                "conflict_fail_closed": True,
                "historical_lessons_preserved": True,
                "current_source_required": True,
                "eligible_memory_ids": sorted(eligible),
                "resolution_fingerprint": resolution.fingerprint(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
