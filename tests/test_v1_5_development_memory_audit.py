from __future__ import annotations

import hashlib
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
TARGET = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_PATH = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json"
PLANNER_PATH = ".autodev/planner-evidence/v1.5-development-memory-proof-001.json"
CONTRACT_PATH = ".autodev/runtime-verification/v15mem1-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem1-001/receipt.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem1-001/report.json"


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fingerprint(payload: object) -> str:
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
        "target_repository": TARGET,
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
                "target_repository": TARGET,
                "source_sha": BASE_SHA,
                "required_probe_ids": [
                    "offline-cli-smoke",
                    "production-import-smoke",
                ],
            },
            "receipt": {
                "status": "VERIFIED",
                "target_repository": TARGET,
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
        evidence_path=SOURCE_PATH,
        evidence_payload=_source_memory_evidence(),
        repository=TARGET,
        current_source_sha=BASE_SHA,
    )
    return bundle.evidence_dict()


def _runtime_contract() -> dict:
    return {
        "schema_version": 1,
        "verification_id": "rv-" + MERGE_SHA,
        "target_repository": TARGET,
        "source_sha": MERGE_SHA,
        "environment": "repository",
        "required_probe_ids": [
            "offline-cli-smoke",
            "production-import-smoke",
        ],
        "max_attempts": 2,
        "timeout_seconds": 300,
    }


def _runtime_receipt() -> dict:
    return {
        "schema_version": 1,
        "verification_id": "rv-" + MERGE_SHA,
        "task_id": "v15mem1-001",
        "target_repository": TARGET,
        "source_sha": MERGE_SHA,
        "contract_fingerprint": HASH_A,
        "registry_fingerprint": HASH_B,
        "policy_fingerprint": HASH_C,
        "status": "VERIFIED",
        "dispatch_count": 1,
    }


def _runtime_report() -> dict:
    return {
        "schema_version": 1,
        "verification_id": "rv-" + MERGE_SHA,
        "contract_fingerprint": HASH_A,
        "source_sha": MERGE_SHA,
        "disposition": "VERIFIED",
        "results": [
            {
                "schema_version": 1,
                "probe_id": "offline-cli-smoke",
                "status": "PASS",
                "source_sha": MERGE_SHA,
                "attempt": 1,
                "detail_code": "offline-cli-pass",
            },
            {
                "schema_version": 1,
                "probe_id": "production-import-smoke",
                "status": "PASS",
                "source_sha": MERGE_SHA,
                "attempt": 1,
                "detail_code": "production-import-pass",
            },
        ],
        "missing_probe_ids": [],
    }


def _runtime_report_wrapper() -> dict:
    return {
        "schema_version": 1,
        "report": _runtime_report(),
        "report_fingerprint": HASH_D,
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


def _store(evidence: dict) -> DevelopmentMemoryStore:
    receipt = evidence["runtime_verification"]["receipt"]
    report_fingerprint = evidence["runtime_verification"]["report_fingerprint"]
    record = DevelopmentMemoryRecord(
        memory_id=MEMORY_ID,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=TARGET,
        source_sha=MERGE_SHA,
        statement=(
            "Trusted runtime verification completed with every required probe passing "
            "against the exact source SHA."
        ),
        task_id="v15mem1-001",
        evidence_paths=(CONTRACT_PATH, RECEIPT_PATH, REPORT_PATH),
        evidence_fingerprints=(
            receipt["contract_fingerprint"],
            _fingerprint(receipt),
            report_fingerprint,
        ),
        tags=("feedback", "runtime", "verified"),
    )
    return merge_memory_records(DevelopmentMemoryStore(), (record,)).store


def _evidence() -> dict:
    memory = _planner_memory()
    evidence = {
        "schema_version": 1,
        "version": "v1.5",
        "request_id": "v1.5-development-memory-proof-001",
        "campaign_id": "v1.5-development-memory-campaign-001",
        "target_repository": TARGET,
        "human_authored_per_task_work_items": False,
        "execution_provenance_clean": True,
        "planner": {
            "workflow_run": 101,
            "planning_only": True,
            "accepted_plan_fingerprint": HASH_A,
            "repository_source_sha": BASE_SHA,
            "development_memory": memory,
        },
        "task": {
            "task_id": "v15mem1-001",
            "base_sha": BASE_SHA,
            "zero_touch_run": 102,
            "jules_cycle_run": 103,
            "pull_request": 18,
            "ci_run": 104,
            "remote_gate_run": 105,
            "remote_monitor_run": 106,
            "head_sha": HEAD_SHA,
            "merge_commit": MERGE_SHA,
            "changed_paths": ["tests/test_models.py"],
        },
        "runtime_verification": {
            "workflow_run": 107,
            "trigger_source": "repository_dispatch",
            "manual_workflow_dispatch": False,
            "workspace_source_sha": MERGE_SHA,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": _runtime_contract(),
            "receipt": _runtime_receipt(),
            "report": _runtime_report(),
            "report_fingerprint": HASH_D,
            "development_memory_feedback": {
                "schema_version": 1,
                "state": "ADDED",
                "memory_id": MEMORY_ID,
                "memory_kind": "VERIFIED_OUTCOME",
                "repository": TARGET,
                "source_sha": MERGE_SHA,
                "store_fingerprint": "0" * 64,
                "record_count": 1,
            },
        },
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "v1.5-development-memory-campaign-001",
                "status": "COMPLETED",
                "task_ids": ["v15mem1-001"],
                "completed_task_ids": ["v15mem1-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }
    store = _store(evidence)
    feedback = evidence["runtime_verification"]["development_memory_feedback"]
    feedback["store_fingerprint"] = store.fingerprint()
    feedback["record_count"] = len(store.ledger.records)
    return evidence


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
            SOURCE_PATH,
            json.dumps(_source_memory_evidence(), indent=2) + "\n",
        )
        _write(
            root,
            PLANNER_PATH,
            json.dumps(_planner_evidence(evidence), indent=2) + "\n",
        )
        _write(root, CONTRACT_PATH, json.dumps(_runtime_contract(), indent=2) + "\n")
        _write(root, RECEIPT_PATH, json.dumps(evidence["runtime_verification"]["receipt"], indent=2) + "\n")
        _write(root, REPORT_PATH, json.dumps(_runtime_report_wrapper(), indent=2) + "\n")
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
                    "Development Memory successor handoff proof",
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
            evidence = _evidence()
            self._fixture(root, evidence)
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
            _write(root, PLANNER_PATH, json.dumps(raw, indent=2) + "\n")
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["planner_evidence_bound"])
            self.assertFalse(result["checks"]["memory_reuse_reproducible"])

    def test_final_memory_claim_must_reproduce_from_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["development_memory"]["memory_ids"] = [
                "mem-" + "e" * 24,
                "mem-" + "f" * 24,
            ]
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
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

    def test_raw_runtime_evidence_must_match_graduation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            raw_receipt = dict(evidence["runtime_verification"]["receipt"])
            raw_receipt["source_sha"] = HEAD_SHA
            _write(root, RECEIPT_PATH, json.dumps(raw_receipt, indent=2) + "\n")
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["runtime_raw_evidence_bound"])

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
