from __future__ import annotations

import json

from ade.development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryEvidence,
    DevelopmentMemoryKind,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    build_development_memory_record,
)


def run_probe() -> dict[str, object]:
    record = build_development_memory_record(
        kind=DevelopmentMemoryKind.SUCCESS_PATTERN,
        repository="M-Osugi1230/autonomous-development-engine",
        scope="v1.5:development-memory-contract",
        summary="Trusted evidence can produce advisory memory without granting execution authority.",
        evidence=(
            DevelopmentMemoryEvidence(
                ref=".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
                fingerprint="a" * 64,
            ),
        ),
        observed_at="2026-09-30T08:43:25+00:00",
    )
    ledger = DevelopmentMemoryLedger().add(record)

    payload = record.to_dict()
    payload["can_grant_execution_authority"] = True
    escalation_rejected = False
    try:
        DevelopmentMemoryRecord.from_dict(payload)
    except DevelopmentMemoryError:
        escalation_rejected = True

    secret_rejected = False
    try:
        build_development_memory_record(
            kind=DevelopmentMemoryKind.FAILURE_LESSON,
            repository="M-Osugi1230/autonomous-development-engine",
            scope="v1.5:development-memory-contract",
            summary="bearer abc.def-ghi",
            evidence=(
                DevelopmentMemoryEvidence(
                    ref=".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
                    fingerprint="b" * 64,
                ),
            ),
            observed_at="2026-09-30T08:43:25+00:00",
        )
    except DevelopmentMemoryError:
        secret_rejected = True

    restored = DevelopmentMemoryLedger.from_dict(ledger.to_dict())
    ok = (
        restored == ledger
        and len(restored.records) == 1
        and restored.records[0].authority.value == "ADVISORY"
        and restored.records[0].can_grant_execution_authority is False
        and restored.records[0].can_expand_write_scope is False
        and restored.records[0].can_bypass_human_wait is False
        and escalation_rejected
        and secret_rejected
    )
    return {
        "ok": ok,
        "schema_version": 1,
        "record_count": len(restored.records),
        "authority": restored.records[0].authority.value,
        "content_fingerprint": restored.records[0].fingerprint(),
        "authority_escalation_rejected": escalation_rejected,
        "secret_rejected": secret_rejected,
    }


if __name__ == "__main__":
    result = run_probe()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)
