from __future__ import annotations

import unittest

from ade.development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_resolution import (
    MemoryDisposition,
    MemorySupersessionRule,
    SupersessionReason,
    memory_subject,
    resolve_development_memory,
)


SHA_A = "a" * 40
SHA_B = "b" * 40
FP_A = "1" * 64
FP_B = "2" * 64
EVIDENCE = ".autodev/campaign-evidence/proof.json"


def runtime_record(
    memory_id: str,
    *,
    source_sha: str,
    statement: str = "Runtime verification passed all required probes.",
    fingerprint: str = FP_A,
    task_id: str = "task-001",
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository="owner/repo",
        source_sha=source_sha,
        statement=statement,
        task_id=task_id,
        evidence_paths=(EVIDENCE,),
        evidence_fingerprints=(fingerprint,),
        tags=("runtime", "verified"),
    )


def campaign_record(
    memory_id: str,
    *,
    source_sha: str,
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=memory_id,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository="owner/repo",
        source_sha=source_sha,
        statement="Campaign completed cleanly.",
        campaign_id="campaign-001",
        task_id="task-001",
        evidence_paths=(EVIDENCE,),
        evidence_fingerprints=(FP_A,),
        tags=("campaign", "verified"),
    )


class DevelopmentMemoryResolutionTests(unittest.TestCase):
    def test_old_source_is_stale_and_current_source_is_active(self) -> None:
        old = runtime_record("memory-old", source_sha=SHA_A)
        current = runtime_record(
            "memory-current",
            source_sha=SHA_B,
            fingerprint=FP_B,
        )
        resolution = resolve_development_memory(
            DevelopmentMemoryLedger(records=(old, current)),
            current_source_shas={"owner/repo": SHA_B},
        )
        dispositions = {
            entry.memory_id: entry.disposition
            for entry in resolution.entries
        }
        self.assertEqual(
            dispositions,
            {
                "memory-current": MemoryDisposition.ACTIVE,
                "memory-old": MemoryDisposition.STALE,
            },
        )
        self.assertEqual(
            tuple(record.memory_id for record in resolution.active_records),
            ("memory-current",),
        )

    def test_multiple_current_memories_for_same_subject_fail_to_conflict(self) -> None:
        first = runtime_record("memory-a", source_sha=SHA_B)
        second = runtime_record(
            "memory-b",
            source_sha=SHA_B,
            statement="Runtime verification passed with a different claimed fact.",
            fingerprint=FP_B,
        )
        resolution = resolve_development_memory(
            DevelopmentMemoryLedger(records=(first, second)),
            current_source_shas={"owner/repo": SHA_B},
        )
        self.assertEqual(resolution.active_records, ())
        self.assertTrue(
            all(
                entry.disposition is MemoryDisposition.CONFLICT
                for entry in resolution.entries
            )
        )

    def test_evidence_backed_supersession_resolves_current_conflict(self) -> None:
        old = runtime_record("memory-old", source_sha=SHA_B)
        new = runtime_record(
            "memory-new",
            source_sha=SHA_B,
            fingerprint=FP_B,
        )
        rule = MemorySupersessionRule(
            rule_id="rule-001",
            old_memory_id="memory-old",
            new_memory_id="memory-new",
            reason=SupersessionReason.CORRECTION,
            evidence_path=".autodev/campaign-evidence/correction.json",
            evidence_fingerprint="3" * 64,
        )
        resolution = resolve_development_memory(
            DevelopmentMemoryLedger(records=(old, new)),
            current_source_shas={"owner/repo": SHA_B},
            supersessions=(rule,),
        )
        entries = {entry.memory_id: entry for entry in resolution.entries}
        self.assertEqual(
            entries["memory-old"].disposition,
            MemoryDisposition.SUPERSEDED,
        )
        self.assertEqual(
            entries["memory-old"].superseded_by,
            "memory-new",
        )
        self.assertEqual(
            entries["memory-new"].disposition,
            MemoryDisposition.ACTIVE,
        )
        self.assertEqual(
            tuple(record.memory_id for record in resolution.active_records),
            ("memory-new",),
        )

    def test_supersession_must_stay_inside_same_subject(self) -> None:
        runtime = runtime_record("memory-runtime", source_sha=SHA_B)
        campaign = campaign_record("memory-campaign", source_sha=SHA_B)
        rule = MemorySupersessionRule(
            rule_id="rule-001",
            old_memory_id="memory-runtime",
            new_memory_id="memory-campaign",
            reason=SupersessionReason.CORRECTION,
            evidence_path=".autodev/campaign-evidence/correction.json",
            evidence_fingerprint="3" * 64,
        )
        with self.assertRaisesRegex(
            DevelopmentMemoryError,
            "cannot cross memory subjects",
        ):
            resolve_development_memory(
                DevelopmentMemoryLedger(records=(runtime, campaign)),
                current_source_shas={"owner/repo": SHA_B},
                supersessions=(rule,),
            )

    def test_supersession_cycles_fail_closed(self) -> None:
        first = runtime_record("memory-a", source_sha=SHA_B)
        second = runtime_record(
            "memory-b",
            source_sha=SHA_B,
            fingerprint=FP_B,
        )
        rules = (
            MemorySupersessionRule(
                rule_id="rule-a",
                old_memory_id="memory-a",
                new_memory_id="memory-b",
                reason=SupersessionReason.CORRECTION,
                evidence_path=".autodev/campaign-evidence/a.json",
                evidence_fingerprint="3" * 64,
            ),
            MemorySupersessionRule(
                rule_id="rule-b",
                old_memory_id="memory-b",
                new_memory_id="memory-a",
                reason=SupersessionReason.CORRECTION,
                evidence_path=".autodev/campaign-evidence/b.json",
                evidence_fingerprint="4" * 64,
            ),
        )
        with self.assertRaisesRegex(DevelopmentMemoryError, "cycle"):
            resolve_development_memory(
                DevelopmentMemoryLedger(records=(first, second)),
                current_source_shas={"owner/repo": SHA_B},
                supersessions=rules,
            )

    def test_missing_or_invalid_current_source_fails_closed(self) -> None:
        record = runtime_record("memory-a", source_sha=SHA_A)
        ledger = DevelopmentMemoryLedger(records=(record,))
        with self.assertRaisesRegex(DevelopmentMemoryError, "missing"):
            resolve_development_memory(
                ledger,
                current_source_shas={},
            )
        with self.assertRaisesRegex(DevelopmentMemoryError, "40-char SHA"):
            resolve_development_memory(
                ledger,
                current_source_shas={"owner/repo": "not-a-sha"},
            )

    def test_subjects_keep_campaign_runtime_recovery_and_decision_separate(self) -> None:
        runtime = runtime_record("memory-runtime", source_sha=SHA_B)
        campaign = campaign_record("memory-campaign", source_sha=SHA_B)
        self.assertEqual(memory_subject(runtime), "runtime:task-001")
        self.assertEqual(memory_subject(campaign), "campaign:campaign-001")


if __name__ == "__main__":
    unittest.main()
