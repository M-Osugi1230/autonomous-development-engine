from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade.development_memory import DevelopmentMemoryRecord, MemoryKind
from ade.development_memory_feedback import build_verified_runtime_feedback_record
from ade.development_memory_planning import build_planning_memory_bundle_from_store
from ade.development_memory_store import DevelopmentMemoryStore, merge_memory_records
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from scripts.v1_5_development_memory_audit import audit


TARGET = "M-Osugi1230/one-minute-thought-experiments"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
MERGE_SHA = "c" * 40
PLAN_HASH = "1" * 64
BOOTSTRAP_MEMORY_ID = "mem-" + "1" * 24
PROOF002_MEMORY_ID = "mem-" + "2" * 24
BOOTSTRAP_PATH = (
    ".autodev/campaign-evidence/"
    "v1.5-development-memory-proof-001-bootstrap.json"
)
PLANNER_PATH = (
    ".autodev/planner-evidence/v1.5-development-memory-proof-002.json"
)
CONTRACT_PATH = ".autodev/runtime-verification/v15mem2-001/contract.json"
RECEIPT_PATH = ".autodev/runtime-verification/v15mem2-001/receipt.json"
REPORT_PATH = ".autodev/runtime-verification/v15mem2-001/report.json"


def _write(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _bootstrap_record() -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id=BOOTSTRAP_MEMORY_ID,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=TARGET,
        source_sha=BASE_SHA,
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
        evidence_fingerprints=("2" * 64, "3" * 64, "4" * 64),
        tags=("feedback", "runtime", "verified"),
    )


def _planning_store() -> DevelopmentMemoryStore:
    return merge_memory_records(
        DevelopmentMemoryStore(),
        (_bootstrap_record(),),
    ).store


def _planner_memory(store: DevelopmentMemoryStore | None = None) -> dict:
    store = store or _planning_store()
    bundle = build_planning_memory_bundle_from_store(
        store=store,
        store_path=".autodev/development-memory.json",
        repository=TARGET,
        current_source_sha=BASE_SHA,
    )
    assert bundle is not None
    return bundle.evidence_dict()


def _contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=TARGET,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


def _receipt() -> RuntimeVerificationReceipt:
    contract = _contract()
    return RuntimeVerificationReceipt(
        verification_id=contract.verification_id,
        task_id="v15mem2-001",
        target_repository=TARGET,
        source_sha=MERGE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="5" * 64,
        policy_fingerprint="6" * 64,
        status="VERIFIED",
        dispatch_count=1,
    )


def _report():
    contract = _contract()
    return evaluate_runtime_verification(
        contract,
        (
            RuntimeProbeResult(
                probe_id="offline-cli-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=MERGE_SHA,
                attempt=1,
                detail_code="offline-cli-pass",
            ),
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=RuntimeProbeStatus.PASS,
                source_sha=MERGE_SHA,
                attempt=1,
                detail_code="production-import-pass",
            ),
        ),
    )


def _report_wrapper() -> dict:
    report = _report()
    return {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


def _proof002_record() -> DevelopmentMemoryRecord:
    record = build_verified_runtime_feedback_record(
        contract=_contract(),
        receipt=_receipt(),
        report=_report(),
        contract_path=CONTRACT_PATH,
        receipt_path=RECEIPT_PATH,
        report_path=REPORT_PATH,
    )
    assert record.task_id == "v15mem2-001"
    return record


def _final_store(
    planning_store: DevelopmentMemoryStore | None = None,
) -> DevelopmentMemoryStore:
    planning_store = planning_store or _planning_store()
    return merge_memory_records(
        planning_store,
        (_proof002_record(),),
    ).store


def _bootstrap_evidence() -> dict:
    record = _bootstrap_record()
    return {
        "schema_version": 1,
        "version": "v1.5-bootstrap",
        "request_id": "v1.5-development-memory-proof-001",
        "campaign_id": "v1.5-development-memory-campaign-001",
        "task_id": "v15mem1-001",
        "target_repository": TARGET,
        "planner_memory": {
            "used": True,
            "authority": "advisory-data-only",
            "execution_authority": False,
            "memory_may_expand_scope": False,
            "memory_may_override_acceptance": False,
        },
        "external_execution": {
            "status": "MERGED",
            "pull_request_url": (
                "https://github.com/M-Osugi1230/"
                "one-minute-thought-experiments/pull/18"
            ),
        },
        "runtime_verification": {
            "verification_id": "rv-" + BASE_SHA,
            "source_sha": BASE_SHA,
            "status": "VERIFIED",
            "dispatch_count": 1,
        },
        "durable_memory_feedback": {
            "memory_id": record.memory_id,
            "memory_fingerprint": record.fingerprint(),
            "store_fingerprint": _planning_store().fingerprint(),
            "store_record_count": 1,
        },
        "successor_request_id": "v1.5-development-memory-proof-002",
        "graduation_eligible": False,
    }


def _planner_evidence(memory: dict) -> dict:
    return {
        "schema_version": 1,
        "request": {
            "request_id": "v1.5-development-memory-proof-002",
        },
        "campaign_id": "v1.5-development-memory-campaign-002",
        "accepted_plan_fingerprint": PLAN_HASH,
        "planning_only": True,
        "workflow_run_id": 201,
        "workflow_run_attempt": 1,
        "repository_source_sha": BASE_SHA,
        "development_memory": memory,
    }


def _evidence(
    *,
    planning_store: DevelopmentMemoryStore | None = None,
) -> dict:
    planning_store = planning_store or _planning_store()
    memory = _planner_memory(planning_store)
    final_store = _final_store(planning_store)
    report_wrapper = _report_wrapper()
    feedback_record = _proof002_record()
    return {
        "schema_version": 1,
        "version": "v1.5",
        "request_id": "v1.5-development-memory-proof-002",
        "campaign_id": "v1.5-development-memory-campaign-002",
        "target_repository": TARGET,
        "human_authored_per_task_work_items": False,
        "execution_provenance_clean": True,
        "planner": {
            "workflow_run": 201,
            "planning_only": True,
            "accepted_plan_fingerprint": PLAN_HASH,
            "repository_source_sha": BASE_SHA,
            "development_memory": memory,
        },
        "task": {
            "task_id": "v15mem2-001",
            "base_sha": BASE_SHA,
            "zero_touch_run": 202,
            "jules_cycle_run": 203,
            "pull_request": 19,
            "ci_run": 204,
            "remote_gate_run": 205,
            "remote_monitor_run": 206,
            "head_sha": HEAD_SHA,
            "merge_commit": MERGE_SHA,
            "changed_paths": ["tests/test_models.py"],
        },
        "runtime_verification": {
            "workflow_run": 207,
            "trigger_source": "repository_dispatch",
            "manual_workflow_dispatch": False,
            "workspace_source_sha": MERGE_SHA,
            "dependency_fingerprint": "7" * 64,
            "recovery_triggered": False,
            "human_wait_triggered": False,
            "contract": _contract().canonical_dict(),
            "receipt": _receipt().canonical_dict(),
            "report": _report().canonical_dict(),
            "report_fingerprint": report_wrapper["report_fingerprint"],
            "development_memory_feedback": {
                "schema_version": 1,
                "state": "ADDED",
                "memory_id": feedback_record.memory_id,
                "memory_kind": "VERIFIED_OUTCOME",
                "repository": TARGET,
                "source_sha": MERGE_SHA,
                "store_fingerprint": final_store.fingerprint(),
                "record_count": len(final_store.ledger.records),
            },
        },
        "manual_campaign_progress_after_goal_submission": False,
        "terminal_snapshot": {
            "campaign": {
                "campaign_id": "v1.5-development-memory-campaign-002",
                "status": "COMPLETED",
                "task_ids": ["v15mem2-001"],
                "completed_task_ids": ["v15mem2-001"],
            },
            "state": {
                "status": "READY",
                "current_task_id": None,
                "failed_task_ids": [],
            },
        },
    }


CI_PROOFS = [
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


class V15DevelopmentMemoryAuditTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        evidence: dict,
        *,
        planning_store: DevelopmentMemoryStore | None = None,
    ) -> None:
        planning_store = planning_store or _planning_store()
        final_store = _final_store(planning_store)
        memory = evidence["planner"]["development_memory"]
        _write(
            root,
            ".autodev/campaign-evidence/v1.5-development-memory-proof-002.json",
            evidence,
        )
        _write(root, BOOTSTRAP_PATH, _bootstrap_evidence())
        _write(root, PLANNER_PATH, _planner_evidence(memory))
        _write(root, ".autodev/development-memory.json", final_store.canonical_dict())
        _write(root, CONTRACT_PATH, _contract().canonical_dict())
        _write(root, RECEIPT_PATH, _receipt().canonical_dict())
        _write(root, REPORT_PATH, _report_wrapper())
        _write(root, ".github/workflows/ci.yml", "\n".join(CI_PROOFS) + "\n")

    def test_complete_durable_store_reuse_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            result = audit(root)
            self.assertTrue(result["v1_5_development_memory_graduated"], result)
            self.assertTrue(all(result["checks"].values()), result)
            self.assertEqual(result["reused_memory_count"], 1)

    def test_later_append_only_memory_does_not_invalidate_graduation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)

            later = DevelopmentMemoryRecord(
                memory_id="mem-" + "3" * 24,
                kind=MemoryKind.VERIFIED_OUTCOME,
                repository=TARGET,
                source_sha=MERGE_SHA,
                statement=(
                    "Trusted runtime verification completed with every required "
                    "probe passing against the exact source SHA."
                ),
                task_id="v16later-001",
                evidence_paths=(
                    ".autodev/runtime-verification/v16later-001/contract.json",
                    ".autodev/runtime-verification/v16later-001/receipt.json",
                    ".autodev/runtime-verification/v16later-001/report.json",
                ),
                evidence_fingerprints=("8" * 64, "9" * 64, "a" * 64),
                tags=("feedback", "runtime", "verified"),
            )
            graduation_store = _final_store()
            live_store = merge_memory_records(
                graduation_store,
                (later,),
            ).store
            _write(
                root,
                ".autodev/development-memory.json",
                live_store.canonical_dict(),
            )

            result = audit(root)
            self.assertTrue(
                result["v1_5_development_memory_graduated"],
                result,
            )
            self.assertTrue(
                result["checks"][
                    "append_only_store_preserves_graduation_records"
                ],
                result,
            )
            self.assertEqual(
                result["final_store_fingerprint"],
                graduation_store.fingerprint(),
            )
            self.assertEqual(
                result["live_store_fingerprint"],
                live_store.fingerprint(),
            )
            self.assertNotEqual(
                result["final_store_fingerprint"],
                result["live_store_fingerprint"],
            )

    def test_bootstrap_feedback_must_be_reused_by_proof002(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["development_memory"]["memory_ids"] = [
                "mem-" + "f" * 24
            ]
            evidence["planner"]["development_memory"]["memory_fingerprints"] = [
                "f" * 64
            ]
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["exact_reused_record_fingerprints"])
            self.assertFalse(result["checks"]["bootstrap_feedback_reused"])

    def test_planning_store_fingerprint_must_match_preproof_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            evidence["planner"]["development_memory"][
                "source_evidence_fingerprint"
            ] = "f" * 64
            self._fixture(root, evidence)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["durable_store_is_planner_source"])

    def test_planner_workflow_run_must_match_raw_planner_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            raw = _planner_evidence(evidence["planner"]["development_memory"])
            raw["workflow_run_id"] = 999
            _write(root, PLANNER_PATH, raw)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["planner_chain"])

    def test_raw_planner_memory_must_match_final_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            raw = _planner_evidence(evidence["planner"]["development_memory"])
            raw["development_memory"] = dict(raw["development_memory"])
            raw["development_memory"]["memory_fingerprints"] = ["f" * 64]
            _write(root, PLANNER_PATH, raw)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["planner_evidence_bound"])

    def test_raw_runtime_evidence_must_match_final_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            changed = _receipt().canonical_dict()
            changed["source_sha"] = BASE_SHA
            _write(root, RECEIPT_PATH, changed)
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["runtime_raw_evidence_bound"])

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

    def test_later_store_cannot_rewrite_graduation_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)

            bootstrap = _bootstrap_record()
            changed_bootstrap = DevelopmentMemoryRecord(
                memory_id=bootstrap.memory_id,
                kind=bootstrap.kind,
                repository=bootstrap.repository,
                source_sha=bootstrap.source_sha,
                statement="Trusted verified outcome content was changed.",
                task_id=bootstrap.task_id,
                evidence_paths=bootstrap.evidence_paths,
                evidence_fingerprints=bootstrap.evidence_fingerprints,
                tags=bootstrap.tags,
            )
            bad_store = DevelopmentMemoryStore(
                ledger=DevelopmentMemoryLedger(
                    records=(changed_bootstrap, _proof002_record())
                )
            )
            _write(
                root,
                ".autodev/development-memory.json",
                bad_store.canonical_dict(),
            )
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(
                result["checks"]["exact_reused_record_fingerprints"]
            )

    def test_final_store_requires_exact_proof002_feedback_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = _evidence()
            self._fixture(root, evidence)
            _write(
                root,
                ".autodev/development-memory.json",
                _planning_store().canonical_dict(),
            )
            result = audit(root)
            self.assertFalse(result["v1_5_development_memory_graduated"])
            self.assertFalse(result["checks"]["runtime_feedback_added"])
            self.assertFalse(result["checks"]["final_feedback_record_bound"])


if __name__ == "__main__":
    unittest.main()
