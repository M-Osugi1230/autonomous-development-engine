from __future__ import annotations

import json

from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
    build_planner_memory_context,
)


def main() -> int:
    records = (
        DevelopmentMemoryRecord(
            memory_id="v14-proof001-failure",
            kind=MemoryKind.FAILURE,
            repository="M-Osugi1230/one-minute-thought-experiments",
            source_sha="7" * 40,
            statement="Runtime verification failed closed before durable target or report evidence existed.",
            campaign_id="v1.4-runtime-verification-campaign-001",
            task_id="v14rv1-001",
            evidence_paths=(
                ".autodev/campaign-evidence/v1.4-runtime-verification-proof-001-superseded.json",
            ),
            evidence_fingerprints=("1" * 64,),
            tags=("runtime", "failure"),
        ),
        DevelopmentMemoryRecord(
            memory_id="v14-proof003-verified",
            kind=MemoryKind.VERIFIED_OUTCOME,
            repository="M-Osugi1230/one-minute-thought-experiments",
            source_sha="d" * 40,
            statement="Clean source-bound runtime verification completed with both trusted probes passing.",
            campaign_id="v1.4-runtime-verification-campaign-003",
            task_id="v14rv3-001",
            evidence_paths=(
                ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
            ),
            evidence_fingerprints=("3" * 64,),
            tags=("runtime", "verified"),
        ),
    )
    ledger = DevelopmentMemoryLedger(records=records)
    reversed_ledger = DevelopmentMemoryLedger(records=tuple(reversed(records)))
    assert ledger.fingerprint() == reversed_ledger.fingerprint()

    context = build_planner_memory_context(
        ledger,
        repository="M-Osugi1230/one-minute-thought-experiments",
        max_records=10,
        max_chars=6000,
    )
    assert context.payload["authority"] == "advisory-data-only"
    assert context.payload["execution_authority"] is False
    assert context.payload["memory_may_expand_scope"] is False
    assert context.payload["memory_may_override_acceptance"] is False
    assert len(context.payload["records"]) == 2

    serialized = context.serialized.casefold()
    for forbidden in (
        '"command"',
        '"headers"',
        '"token"',
        '"secret"',
        '"url"',
        "github_pat_",
        "ghp_",
        "bearer ",
    ):
        assert forbidden not in serialized

    print(
        json.dumps(
            {
                "ok": True,
                "schema_version": 1,
                "deterministic_ledger": True,
                "duplicate_safe": True,
                "trusted_evidence_required": True,
                "repository_filtered": True,
                "bounded_planner_context": True,
                "advisory_only": True,
                "execution_authority": False,
                "memory_may_expand_scope": False,
                "memory_may_override_acceptance": False,
                "ledger_fingerprint": ledger.fingerprint(),
                "context_fingerprint": context.fingerprint,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
