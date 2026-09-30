from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade.development_memory import DevelopmentMemoryRecord, MemoryKind
from ade.development_memory_planning import build_planning_memory_bundle
from ade.development_memory_store import DevelopmentMemoryStore, merge_memory_records
from scripts.v1_5_development_memory_audit import audit


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
HASH_A = "1" * 64
HASH_B = "2" * 64
HASH_C = "3" * 64
HASH_D = "4" * 64
MEMORY_ID = "mem-" + "d" * 24


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fingerprint(payload: object) -> str:
    import hashlib

    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_memory_evidence() -> dict:
    return {
        "schema_version": 1,
        "version": "v1.4",
        "campaign_id": "v1.4-runtime-verification-campaign-003",
        "target_repository": "M-Osugi1230/one-minute-thought-experiments",
        "terminal_status": "COMPLETED",
        "failed_tasks": 0,
        "task": {
            "task_id": "v14rv3-001",
            "merge_commit": BASE_SHA,
        },
        "runtime_verification": {
            "workspace_source_sha": BASE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": {
                "target_repository": "M-Osugi1230/one-minute-thought-experiments",
                "source_sha": BASE_SHA,
                "required_probe_ids": [
                    "offline-cli-smoke",
                    "production-import-smoke",
                ],
            },
            "receipt": {
                "status": "VERIFIED",
                "target_repository": "M-Osugi1230/one-minute-thought-experiments",
                "task_id": "v14rv3-001",
                "source_sha": BASE_SHA,
            },
            "report": {
                "disposition": "VERIFIED",
                "source_sha": BASE_SHA,
                "results": [
                    {
                        "probe_id": "offline-cli-smoke",
                        "status": "PASS",
                        "source_sha": BASE_SHA,
                    },
                    {
                        "probe_id": "production-import-smoke",
                        "status": "PASS",
                        "source_sha": BASE_SHA,
                    },
                ],
            },
        },
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "v1.4-runtime-verification-campaign-003",
                "status": "COMPLETED",
                "task_ids": ["v14rv3-001"],
                "completed_task_ids": ["v14rv3-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


def _planner_memory() -> dict:
    bundle = build_planning_memory_bundle(
        evidence_path=(
            ".autodev/campaign-evidence/"
            "v1.4-runtime-verification-proof-003.json"
        ),
        evidence_payload=_source_memory_evidence(),
        repository="M-Osugi1230/one-minute-thought-experiments",
        current_source_sha=BASE_SHA,
    )
    return bundle.evidence_dict()


def _store(evidence: dict) -> DevelopmentMemoryStore:
    runtime = evidence["runtime_verification"]
    receipt = runtime["receipt"]
    record = DevelopmentMemoryRecord(
        memory_id=MEMORY_ID,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha=MERGE_SHA,
        statement=(
            "Trusted runtime verification completed with every required probe passing "
            "against the exact source SHA."
        ),
        task_id="v15mem1-001",
        evidence_paths=(
            ".autodev/runtime-verification/v15mem1-001/contract.json",
            ".autodev/runtime-verification/v15mem1-001/receipt.json",
            ".autodev/runtime-verification/v15mem1-001/report.json",
        ),
        evidence_fingerprints=(
            receipt["contract_fingerprint"],
            _fingerprint(receipt),
            runtime["report_fingerprint"],
        ),
        tags=("feedback", "runtime", "verified"),
    )
    return merge_memory_records(DevelopmentMemoryStore(), (record,)).store


def _planner_evidence(evidence: dict) -> dict:
    planner = evidence["planner"]
    return {
        "schema_version": 1,
        "campaign_id": evidence["campaign_id"],
        "accepted_plan_fingerprint": planner["accepted_plan_fingerprint"],
        "planning_only": True,
        "repository_source_sha": BASE_SHA,
        "development_memory": planner["development_memory"],
    }
    store = _store(evidence)
    feedback = evidence["runtime_verification"]["development_memory_feedback"]
    feedback["store_fingerprint"] = store.fingerprint()
    feedback["record_count"] = len(store.ledger.records)
    return evidence



class V15DevelopmentMemoryAuditTests(unittest.TestCase):
    def _fixture(self, root: Path, evidence: dict) -> None:
        _write(
            root,
            ".autodev/campaign-evidence/v1.5-development-memory-proof-001.json",
            json.dumps(evidence, indent=2) + "\n",
        )
        _write(
            root,
            ".autodev/development-memory.json",
            json.dumps(_store(evidence).canonical_dict(), indent=2) + "\n",
        )
        _write(
            root,
            ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json",
            json.dumps(_source_memory_evidence(), indent=2) + "\n",
        )
        _write(
            root,
            ".autodev/planner-evidence/v1.5-development-memory-proof-001.json",
            json.dumps(_planner_evidence(evidence), indent=2) + "\n",
        )
        _write(
            root,
            ".github/workflows/ci.yml",
            "\n".join(
                [
                    "Zero-Touch Start proof",
                    "Execution lease duplicate-dispatch proof",
                    "Autonomous Planner proof",
                    "Repository Intelligence proof",
                    "Development Memory proof",
                    "Development Memory extraction proof",
                    "Development Memory resolution proof",
                    "Development Memory retrieval proof",
                    "Development Memory planner integration proof",
                    "Development Memory feedback lifecycle proof",
                    "Runtime Verification post-merge trigger proof",
                    "Runtime Verification bounded execution proof",
                    "Runtime Verification real repository probe proof",
                    "Runtime Verification target adapter proof",
                    "Runtime Verification failure containment proof",
                    "Remote Repository Loop proof",
                    "Human decision boundary proof",
                ]
            ),
        )

    def test_complete_memory_reuse_and_feedback_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._fixture(root, _evidence())
            result = audit(root)
            self.assertTrue(result["v1_5_development_memory_graduated"], result)
            self.assertTrue(all(result["checks"].values()), result)

    def test_final_memory_claim_must_match_raw_planner_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            raw = _planner_evidence(evidence)
            raw["development_memory"] = dict(raw["development_memory"])
            raw["development_memory"]["memory_ids"] = ["mem-" + "f" * 24]
            _write(
                root,
                ".autodev/planner-evidence/v1.5-development-memory-proof-001.json",
                json.dumps(raw, indent=2) + "\n",
            )
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["planner_evidence_bound"])
            self.assertFalse(result["checks"]["memory_reuse_reproducible"])

    def test_feedback_store_fingerprint_must_match_durable_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["development_memory_feedback"][
                "store_fingerprint"
            ] = HASH_A
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["runtime_memory_feedback"])

    def test_planner_without_memory_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["development_memory"]["used"] = False
            evidence["planner"]["development_memory"]["retrieved_record_count"] = 0
            evidence["planner"]["development_memory"]["memory_ids"] = []
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["memory_reused"])

    def test_stale_memory_source_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["development_memory"]["current_source_sha"] = HEAD_SHA
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["memory_reused"])

    def test_missing_runtime_feedback_record_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["development_memory_feedback"][
                "memory_id"
            ] = "mem-" + "e" * 24
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["durable_store_feedback_record"])

    def test_runtime_failure_or_manual_progress_cannot_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["runtime_verification"]["receipt"]["status"] = "HUMAN_WAIT"
            evidence["manual_campaign_progress_after_goal_submission"] = True
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["runtime_exact_merge_sha"])
            self.assertFalse(result["checks"]["no_manual_campaign_progress"])


if __name__ == "__main__":
    unittest.main()
