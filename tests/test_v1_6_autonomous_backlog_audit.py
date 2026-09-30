from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_extraction import (
    extract_verified_memory_followup_candidate,
)
from ade.autonomous_backlog_feedback import build_verified_backlog_retirement
from ade.autonomous_backlog_goal import (
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from ade.autonomous_backlog_resolution import resolve_autonomous_backlog
from ade.autonomous_backlog_selection import select_next_backlog_candidate
from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_store import DevelopmentMemoryStore
from ade.remote_execution import RemoteExecutionReceipt
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt
from scripts.v1_6_autonomous_backlog_audit import (
    ACCEPTED_PLAN_PATH,
    BACKLOG_PATH,
    CAMPAIGN_PATH,
    EVIDENCE_PATH,
    HANDOFF_PATH,
    PLANNING_GOAL_PATH,
    POLICY_PATH,
    POST_RESOLUTION_PATH,
    POST_SELECTION_PATH,
    PROOF_PROVENANCE_PATH,
    REMOTE_PATH,
    RESOLUTION_PATH,
    RETIREMENT_PATH,
    SELECTION_PATH,
    SOURCE_STORE_PATH,
    STATE_PATH,
    TARGET_REPOSITORY,
    audit,
)


BASE_SHA = "a" * 40
MERGE_SHA = "b" * 40
HEAD_SHA = "c" * 40
TASK_ID = "abgproof-task-001"
MEMORY_ID = "mem-v16-source-001"
PLAN_FP = "d" * 64
CONTRACT_PATH = f".autodev/runtime-verification/{TASK_ID}/contract.json"
RECEIPT_PATH = f".autodev/runtime-verification/{TASK_ID}/receipt.json"
REPORT_PATH = f".autodev/runtime-verification/{TASK_ID}/report.json"


CI_PROOFS = [
    "Autonomous Backlog proof",
    "Autonomous Backlog trusted extraction proof",
    "Autonomous Backlog resolution proof",
    "Autonomous Backlog selection proof",
    "Autonomous Backlog PlanningGoal handoff proof",
    "Autonomous Backlog verified retirement proof",
    "Autonomous Backlog successor gate proof",
    "Autonomous Backlog finalizer proof",
    "Autonomous Planner proof",
    "Repository Intelligence proof",
    "Development Memory proof",
    "Development Memory feedback lifecycle proof",
    "Runtime Verification post-merge trigger proof",
    "Runtime Verification bounded execution proof",
    "Runtime Verification real repository probe proof",
    "Remote Repository Loop proof",
    "Human decision boundary proof",
    "ADE v1.5 Development Memory Graduation audit",
]


def write(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def source_store() -> DevelopmentMemoryStore:
    record = DevelopmentMemoryRecord(
        memory_id=MEMORY_ID,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=TARGET_REPOSITORY,
        source_sha=BASE_SHA,
        statement=(
            "Trusted runtime verification completed with every required probe "
            "passing against the exact source SHA."
        ),
        task_id="v15-final-task",
        evidence_paths=(
            ".autodev/runtime-verification/v15-final-task/contract.json",
            ".autodev/runtime-verification/v15-final-task/receipt.json",
            ".autodev/runtime-verification/v15-final-task/report.json",
        ),
        evidence_fingerprints=("1" * 64, "2" * 64, "3" * 64),
        tags=("feedback", "runtime", "verified"),
    )
    return DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=(record,))
    )


def policy() -> BacklogPlanningPolicy:
    return BacklogPlanningPolicy(
        repository=TARGET_REPOSITORY,
        base_branch="main",
        allowed_path_prefixes=("tests",),
        request_prefix="abgproof",
        min_tasks=1,
        max_tasks=1,
    )


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + MERGE_SHA,
        target_repository=TARGET_REPOSITORY,
        source_sha=MERGE_SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


def receipt(*, status: str = "VERIFIED") -> RuntimeVerificationReceipt:
    value = contract()
    return RuntimeVerificationReceipt(
        verification_id=value.verification_id,
        task_id=TASK_ID,
        target_repository=TARGET_REPOSITORY,
        source_sha=MERGE_SHA,
        contract_fingerprint=value.fingerprint(),
        registry_fingerprint="4" * 64,
        policy_fingerprint="5" * 64,
        status=status,
        dispatch_count=1,
    )


def report_wrapper() -> dict:
    value = contract()
    report = evaluate_runtime_verification(
        value,
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
    return {
        "schema_version": 1,
        "report": report.canonical_dict(),
        "report_fingerprint": report.fingerprint(),
        "attempts_by_probe": [
            {"probe_id": "offline-cli-smoke", "attempts": 1},
            {"probe_id": "production-import-smoke", "attempts": 1},
        ],
    }


def build_chain():
    store = source_store()
    candidate = extract_verified_memory_followup_candidate(
        store_path=SOURCE_STORE_PATH,
        store_payload=store.canonical_dict(),
        memory_id=MEMORY_ID,
        source_phase="v1.6-autonomous-backlog",
    )
    backlog = AutonomousBacklog(candidates=(candidate,))
    resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: BASE_SHA},
    )
    selection = select_next_backlog_candidate(
        backlog,
        resolution,
        repository=TARGET_REPOSITORY,
        source_sha=BASE_SHA,
    )
    handoff = build_planning_goal_handoff(
        backlog,
        resolution,
        selection,
        policy=policy(),
    )
    campaign = {
        "schema_version": 1,
        "campaign_id": handoff.request.campaign_id,
        "status": "COMPLETED",
        "task_ids": [TASK_ID],
        "completed_task_ids": [TASK_ID],
        "goal": handoff.request.goal,
    }
    state = {
        "schema_version": 1,
        "project_id": "ade-proof",
        "status": "READY",
        "current_task_id": None,
        "completed_task_ids": [TASK_ID],
        "failed_task_ids": [],
        "metadata": {
            "phase": "v1.6-autonomous-backlog",
            "planning_request_id": handoff.request.request_id,
            "campaign_id": handoff.request.campaign_id,
            "target_repository": TARGET_REPOSITORY,
        },
    }
    remote = RemoteExecutionReceipt(
        task_id=TASK_ID,
        target_repository=TARGET_REPOSITORY,
        pull_request_url=f"https://github.com/{TARGET_REPOSITORY}/pull/21",
        recorded_at="2026-10-01T02:00:00+00:00",
        status="MERGED",
    )
    retirement = build_verified_backlog_retirement(
        backlog=backlog,
        handoff=handoff,
        campaign_payload=campaign,
        state_payload=state,
        remote_execution_payload=remote.to_dict(),
        runtime_contract_payload=contract().canonical_dict(),
        runtime_receipt_payload=receipt().canonical_dict(),
        runtime_report_wrapper_payload=report_wrapper(),
        handoff_path=HANDOFF_PATH,
        campaign_path=CAMPAIGN_PATH,
        state_path=STATE_PATH,
        remote_execution_path=REMOTE_PATH,
        runtime_contract_path=CONTRACT_PATH,
        runtime_receipt_path=RECEIPT_PATH,
        runtime_report_path=REPORT_PATH,
    )
    post_resolution = resolve_autonomous_backlog(
        backlog,
        current_sources={TARGET_REPOSITORY: MERGE_SHA},
        retirements=(retirement,),
    )
    post_selection = select_next_backlog_candidate(
        backlog,
        post_resolution,
        repository=TARGET_REPOSITORY,
        source_sha=MERGE_SHA,
    )
    return {
        "store": store,
        "candidate": candidate,
        "backlog": backlog,
        "resolution": resolution,
        "selection": selection,
        "handoff": handoff,
        "campaign": campaign,
        "state": state,
        "remote": remote,
        "retirement": retirement,
        "post_resolution": post_resolution,
        "post_selection": post_selection,
    }


def evidence(chain: dict) -> dict:
    handoff = chain["handoff"]
    report = report_wrapper()
    return {
        "schema_version": 1,
        "version": "v1.6",
        "target_repository": TARGET_REPOSITORY,
        "human_authored_per_task_work_items": False,
        "manual_campaign_progress_after_goal_submission": False,
        "execution_provenance_clean": True,
        "source_memory": {
            "path": SOURCE_STORE_PATH,
            "memory_id": MEMORY_ID,
            "memory_fingerprint": chain["store"].ledger.records[0].fingerprint(),
            "store_fingerprint": chain["store"].fingerprint(),
        },
        "candidate": {
            "candidate_id": chain["candidate"].candidate_id,
            "candidate_fingerprint": chain["candidate"].fingerprint(),
            "backlog_fingerprint": chain["backlog"].fingerprint(),
        },
        "planning": {
            "resolution_fingerprint": chain["resolution"].fingerprint(),
            "selection_fingerprint": chain["selection"].fingerprint(),
            "policy_fingerprint": policy().fingerprint(),
            "handoff_fingerprint": handoff.fingerprint(),
            "request_id": handoff.request.request_id,
            "campaign_id": handoff.request.campaign_id,
            "planner_workflow_run": 601,
        },
        "task": {
            "task_id": TASK_ID,
            "zero_touch_run": 602,
            "implementation_run": 603,
            "pull_request": 21,
            "ci_run": 604,
            "remote_gate_run": 605,
            "remote_monitor_run": 606,
            "head_sha": HEAD_SHA,
            "merge_sha": MERGE_SHA,
            "changed_paths": ["tests/test_models.py"],
        },
        "runtime_verification": {
            "workflow_run": 607,
            "manual_workflow_dispatch": False,
            "contract_path": CONTRACT_PATH,
            "receipt_path": RECEIPT_PATH,
            "report_path": REPORT_PATH,
            "report_fingerprint": report["report_fingerprint"],
        },
        "retirement": {
            "retirement_id": chain["retirement"].retirement_id,
            "retirement_fingerprint": chain["retirement"].fingerprint(),
            "candidate_id": chain["candidate"].candidate_id,
        },
        "post_retirement": {
            "resolution_fingerprint": chain["post_resolution"].fingerprint(),
            "selection_fingerprint": chain["post_selection"].fingerprint(),
            "selected_candidate_id": None,
        },
    }


def fixture(root: Path) -> dict:
    chain = build_chain()
    handoff = chain["handoff"]
    planner_path = (
        f".autodev/planner-evidence/{handoff.request.request_id}.json"
    )
    planner = {
        "schema_version": 1,
        "request": handoff.request.to_dict(),
        "campaign_id": handoff.request.campaign_id,
        "accepted_plan_fingerprint": PLAN_FP,
        "planning_only": True,
        "workflow_run_id": 601,
        "repository_source_sha": BASE_SHA,
    }
    accepted_plan = {
        "schema_version": 1,
        "status": "ACCEPTED",
        "fingerprint": PLAN_FP,
        "plan": {
            "schema_version": 1,
            "goal": handoff.request.goal,
            "tasks": [
                {
                    "task_id": TASK_ID,
                    "title": "Add bounded regression coverage",
                    "outcome": "Add bounded regression coverage.",
                    "allowed_paths": ["tests/test_models.py"],
                    "new_paths": [],
                    "depends_on": [],
                    "acceptance": ["Repository CI remains green"],
                    "human_only": False,
                    "human_reason": None,
                }
            ],
        },
    }

    write(root, SOURCE_STORE_PATH, chain["store"].canonical_dict())
    write(root, BACKLOG_PATH, chain["backlog"].canonical_dict())
    write(root, RESOLUTION_PATH, chain["resolution"].canonical_dict())
    write(root, SELECTION_PATH, chain["selection"].canonical_dict())
    write(root, POLICY_PATH, policy().canonical_dict())
    write(root, HANDOFF_PATH, handoff.canonical_dict())
    write(root, PLANNING_GOAL_PATH, handoff.request.to_dict())
    write(root, planner_path, planner)
    write(root, ACCEPTED_PLAN_PATH, accepted_plan)
    write(root, CAMPAIGN_PATH, chain["campaign"])
    write(root, STATE_PATH, chain["state"])
    write(root, REMOTE_PATH, chain["remote"].to_dict())
    write(root, CONTRACT_PATH, contract().canonical_dict())
    write(root, RECEIPT_PATH, receipt().canonical_dict())
    write(root, REPORT_PATH, report_wrapper())
    write(root, RETIREMENT_PATH, chain["retirement"].canonical_dict())
    write(
        root,
        POST_RESOLUTION_PATH,
        chain["post_resolution"].canonical_dict(),
    )
    write(
        root,
        POST_SELECTION_PATH,
        chain["post_selection"].canonical_dict(),
    )
    write(
        root,
        PROOF_PROVENANCE_PATH,
        {
            "schema_version": 1,
            "task_id": TASK_ID,
            "planner_workflow_run": 601,
            "zero_touch_receipt": {
                "schema_version": 1,
                "campaign_id": handoff.request.campaign_id,
                "task_id": TASK_ID,
                "status": "DISPATCHED",
                "dispatch_count": 1,
                "source": "repository_dispatch",
                "run_id": "602",
            },
            "runtime_provenance": {
                "schema_version": 1,
                "task_id": TASK_ID,
                "pull_request_number": 21,
                "pull_request_head_sha": HEAD_SHA,
                "trusted_merge_sha": MERGE_SHA,
                "implementation_workflow_run_id": 603,
                "remote_monitor_workflow_run_id": 606,
                "runtime_workflow_run_id": 607,
                "runtime_workflow_event": "repository_dispatch",
            },
            "target_pull_request": {
                "pull_request": 21,
                "base_sha": BASE_SHA,
                "head_sha": HEAD_SHA,
                "merge_sha": MERGE_SHA,
                "changed_paths": ["tests/test_models.py"],
                "ci_run": 604,
                "remote_gate_run": 605,
            },
        },
    )
    write(root, EVIDENCE_PATH, evidence(chain))
    write(root, ".github/workflows/ci.yml", "\n".join(CI_PROOFS) + "\n")
    return chain


class V16AutonomousBacklogAuditTests(unittest.TestCase):
    def test_complete_reconstructed_chain_graduates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            result = audit(root)
            self.assertTrue(result["v1_6_autonomous_backlog_graduated"], result)
            self.assertTrue(all(result["checks"].values()), result)

    def test_source_memory_fingerprint_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            value = json.loads((root / EVIDENCE_PATH).read_text())
            value["source_memory"]["memory_fingerprint"] = "f" * 64
            write(root, EVIDENCE_PATH, value)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["source_store_bound"])

    def test_candidate_tampering_breaks_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = fixture(root)
            payload = chain["backlog"].canonical_dict()
            payload["candidates"][0]["statement"] = (
                "Trusted verified outcome was replaced by another bounded follow-up."
            )
            write(root, BACKLOG_PATH, payload)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["candidate_reconstructed"])

    def test_policy_bound_alternate_tests_path_can_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            accepted = json.loads((root / ACCEPTED_PLAN_PATH).read_text())
            accepted["plan"]["tasks"][0]["allowed_paths"] = [
                "tests/test_pipeline.py"
            ]
            write(root, ACCEPTED_PLAN_PATH, accepted)

            proof = json.loads((root / EVIDENCE_PATH).read_text())
            proof["task"]["changed_paths"] = ["tests/test_pipeline.py"]
            write(root, EVIDENCE_PATH, proof)

            provenance = json.loads(
                (root / PROOF_PROVENANCE_PATH).read_text()
            )
            provenance["target_pull_request"]["changed_paths"] = [
                "tests/test_pipeline.py"
            ]
            write(root, PROOF_PROVENANCE_PATH, provenance)

            result = audit(root)
            self.assertTrue(
                result["checks"]["accepted_plan_bounded"],
                result,
            )
            self.assertTrue(
                result["v1_6_autonomous_backlog_graduated"],
                result,
            )

    def test_canonical_omitted_task_defaults_can_graduate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            accepted = json.loads((root / ACCEPTED_PLAN_PATH).read_text())
            task = accepted["plan"]["tasks"][0]
            task.pop("new_paths", None)
            task.pop("human_only", None)
            write(root, ACCEPTED_PLAN_PATH, accepted)

            result = audit(root)
            self.assertTrue(
                result["checks"]["accepted_plan_bounded"],
                result,
            )
            self.assertTrue(
                result["v1_6_autonomous_backlog_graduated"],
                result,
            )

    def test_accepted_plan_scope_expansion_blocks_graduation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            payload = json.loads((root / ACCEPTED_PLAN_PATH).read_text())
            payload["plan"]["tasks"][0]["allowed_paths"] = [
                "tests/test_models.py",
                "src/ade/unsafe.py",
            ]
            write(root, ACCEPTED_PLAN_PATH, payload)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["accepted_plan_bounded"])

    def test_runtime_failure_blocks_retirement_and_graduation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            payload = receipt(status="FAILED").canonical_dict()
            write(root, RECEIPT_PATH, payload)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["runtime_verified"])
            self.assertFalse(result["checks"]["retirement_reconstructed"])

    def test_retirement_record_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            payload = json.loads((root / RETIREMENT_PATH).read_text())
            payload["verified_source_sha"] = "e" * 40
            write(root, RETIREMENT_PATH, payload)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["retirement_reconstructed"])

    def test_post_retirement_candidate_cannot_be_reselected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = fixture(root)
            raw = chain["post_selection"].canonical_dict()
            raw["selected_candidate_id"] = chain["candidate"].candidate_id
            raw["eligible_candidate_ids"] = [chain["candidate"].candidate_id]
            write(root, POST_SELECTION_PATH, raw)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(
                result["checks"]["post_retirement_no_reselection"]
            )

    def test_provenance_snapshot_tampering_blocks_graduation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            payload = json.loads((root / PROOF_PROVENANCE_PATH).read_text())
            payload["runtime_provenance"]["trusted_merge_sha"] = "f" * 40
            write(root, PROOF_PROVENANCE_PATH, payload)
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertFalse(result["checks"]["provenance_snapshot_bound"])

    def test_missing_mandatory_ci_proof_blocks_graduation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root)
            write(
                root,
                ".github/workflows/ci.yml",
                "\n".join(CI_PROOFS[:-1]) + "\n",
            )
            result = audit(root)
            self.assertFalse(result["v1_6_autonomous_backlog_graduated"])
            self.assertIn(
                "ADE v1.5 Development Memory Graduation audit",
                result["missing_proofs"],
            )


if __name__ == "__main__":
    unittest.main()
