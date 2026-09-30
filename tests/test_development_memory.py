from __future__ import annotations

import unittest

from ade.development_memory import (
    DevelopmentMemoryAuthority,
    DevelopmentMemoryError,
    DevelopmentMemoryEvidence,
    DevelopmentMemoryKind,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    build_development_memory_record,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
OBSERVED = "2026-09-30T08:43:25+00:00"


def build_record(
    *,
    kind: DevelopmentMemoryKind = DevelopmentMemoryKind.SUCCESS_PATTERN,
    summary: str = "Exact source-SHA runtime verification passed both trusted probes.",
    ref: str = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
    fingerprint: str = HASH_A,
):
    return build_development_memory_record(
        kind=kind,
        repository="M-Osugi1230/autonomous-development-engine",
        scope="v1.4:runtime-verification",
        summary=summary,
        evidence=(
            DevelopmentMemoryEvidence(
                ref=ref,
                fingerprint=fingerprint,
            ),
        ),
        observed_at=OBSERVED,
    )


class DevelopmentMemoryTests(unittest.TestCase):
    def test_record_is_deterministic_source_bound_and_advisory_only(self) -> None:
        first = build_record()
        second = build_record()

        self.assertEqual(first, second)
        self.assertEqual(first.memory_id, second.memory_id)
        self.assertEqual(first.authority, DevelopmentMemoryAuthority.ADVISORY)
        self.assertFalse(first.can_grant_execution_authority)
        self.assertFalse(first.can_expand_write_scope)
        self.assertFalse(first.can_bypass_human_wait)
        self.assertEqual(len(first.fingerprint()), 64)
        self.assertEqual(
            first.evidence[0].ref,
            ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
        )

    def test_record_round_trip_preserves_fingerprint(self) -> None:
        record = build_record()
        restored = DevelopmentMemoryRecord.from_dict(record.to_dict())
        self.assertEqual(restored, record)
        self.assertEqual(restored.fingerprint(), record.fingerprint())

    def test_authority_escalation_is_rejected(self) -> None:
        payload = build_record().to_dict()
        payload["can_grant_execution_authority"] = True
        with self.assertRaisesRegex(
            DevelopmentMemoryError,
            "never grant execution authority",
        ):
            DevelopmentMemoryRecord.from_dict(payload)

        payload = build_record().to_dict()
        payload["can_expand_write_scope"] = True
        with self.assertRaisesRegex(
            DevelopmentMemoryError,
            "never expand write scope",
        ):
            DevelopmentMemoryRecord.from_dict(payload)

        payload = build_record().to_dict()
        payload["can_bypass_human_wait"] = True
        with self.assertRaisesRegex(
            DevelopmentMemoryError,
            "never bypass HUMAN_WAIT",
        ):
            DevelopmentMemoryRecord.from_dict(payload)

    def test_secret_traceback_and_untrusted_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(DevelopmentMemoryError, "secret"):
            build_record(summary="Observed bearer abc.def-ghi during a run")

        with self.assertRaisesRegex(DevelopmentMemoryError, "tracebacks"):
            build_record(summary="Traceback (most recent call last): failure")

        with self.assertRaisesRegex(DevelopmentMemoryError, "trusted .autodev"):
            build_record(ref="provider/raw-output.json")

    def test_evidence_fingerprint_and_paths_fail_closed(self) -> None:
        with self.assertRaisesRegex(DevelopmentMemoryError, "SHA-256"):
            build_record(fingerprint="not-a-fingerprint")

        with self.assertRaisesRegex(DevelopmentMemoryError, "normalized"):
            build_record(
                ref=".autodev/campaign-evidence/../secrets.json",
            )

    def test_memory_id_tampering_is_rejected(self) -> None:
        payload = build_record().to_dict()
        payload["memory_id"] = "mem-" + "0" * 24
        with self.assertRaisesRegex(
            DevelopmentMemoryError,
            "trusted content fingerprint",
        ):
            DevelopmentMemoryRecord.from_dict(payload)

    def test_ledger_is_bounded_deterministic_and_idempotent(self) -> None:
        later = build_development_memory_record(
            kind=DevelopmentMemoryKind.FAILURE_LESSON,
            repository="M-Osugi1230/autonomous-development-engine",
            scope="v1.4:runtime-verification",
            summary="A controller CI failure must not be attributed to an external task.",
            evidence=(
                DevelopmentMemoryEvidence(
                    ref=".autodev/campaign-evidence/v1.4-runtime-verification-proof-002-excluded.json",
                    fingerprint=HASH_B,
                ),
            ),
            observed_at="2026-09-30T08:44:00+00:00",
        )
        first = build_record()
        ledger = DevelopmentMemoryLedger(records=(later, first))

        self.assertEqual(ledger.records, (first, later))
        self.assertIs(ledger.add(first), ledger)
        restored = DevelopmentMemoryLedger.from_dict(ledger.to_dict())
        self.assertEqual(restored, ledger)

    def test_ledger_rejects_duplicate_persisted_records(self) -> None:
        record = build_record()
        with self.assertRaisesRegex(DevelopmentMemoryError, "duplicate memory_id"):
            DevelopmentMemoryLedger(records=(record, record))


if __name__ == "__main__":
    unittest.main()
