from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ade.development_memory import DevelopmentMemoryLedger
from ade.development_memory_feedback import (
    build_verified_runtime_feedback_record,
    runtime_report_from_wrapper,
)
from ade.development_memory_store import DevelopmentMemoryStore
from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


DEFAULT_EVIDENCE = (
    ".autodev/campaign-evidence/v1.5-development-memory-proof-002.json"
)
BOOTSTRAP_EVIDENCE = (
    ".autodev/campaign-evidence/"
    "v1.5-development-memory-proof-001-bootstrap.json"
)
PLANNER_EVIDENCE = (
    ".autodev/planner-evidence/v1.5-development-memory-proof-002.json"
)
STORE_PATH = ".autodev/development-memory.json"
RUNTIME_CONTRACT = ".autodev/runtime-verification/v15mem2-001/contract.json"
RUNTIME_RECEIPT = ".autodev/runtime-verification/v15mem2-001/receipt.json"
RUNTIME_REPORT = ".autodev/runtime-verification/v15mem2-001/report.json"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
REQUEST_ID = "v1.5-development-memory-proof-002"
CAMPAIGN_ID = "v1.5-development-memory-campaign-002"
TASK_ID = "v15mem2-001"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CI_PROOFS = (
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
)


def _load(root: Path, relative: str) -> dict[str, Any]:
    payload = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return payload


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _sha40(value: object) -> bool:
    return isinstance(value, str) and SHA40.fullmatch(value) is not None


def _sha256(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _memory_pairs(memory: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    ids = memory.get("memory_ids")
    fingerprints = memory.get("memory_fingerprints")
    if not isinstance(ids, list) or not isinstance(fingerprints, list):
        return ()
    if not ids or len(ids) != len(fingerprints):
        return ()
    if any(not isinstance(memory_id, str) or not memory_id for memory_id in ids):
        return ()
    if any(not _sha256(value) for value in fingerprints):
        return ()
    pairs = tuple(zip(ids, fingerprints, strict=True))
    if len({memory_id for memory_id, _ in pairs}) != len(pairs):
        return ()
    return pairs


def audit(
    root: Path,
    *,
    evidence_path: str = DEFAULT_EVIDENCE,
    store_path: str = STORE_PATH,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    bootstrap = _load(root, BOOTSTRAP_EVIDENCE)
    planner_evidence = _load(root, PLANNER_EVIDENCE)
    raw_contract_payload = _load(root, RUNTIME_CONTRACT)
    raw_receipt_payload = _load(root, RUNTIME_RECEIPT)
    raw_report_wrapper = _load(root, RUNTIME_REPORT)
    store = DevelopmentMemoryStore.from_dict(_load(root, store_path))
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    planner = evidence.get("planner")
    planner = planner if isinstance(planner, dict) else {}
    memory = planner.get("development_memory")
    memory = memory if isinstance(memory, dict) else {}
    task = evidence.get("task")
    task = task if isinstance(task, dict) else {}
    runtime = evidence.get("runtime_verification")
    runtime = runtime if isinstance(runtime, dict) else {}
    contract = runtime.get("contract")
    contract = contract if isinstance(contract, dict) else {}
    receipt = runtime.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    report = runtime.get("report")
    report = report if isinstance(report, dict) else {}
    feedback = runtime.get("development_memory_feedback")
    feedback = feedback if isinstance(feedback, dict) else {}
    terminal = evidence.get("terminal_snapshot")
    terminal = terminal if isinstance(terminal, dict) else {}
    campaign = terminal.get("campaign")
    campaign = campaign if isinstance(campaign, dict) else {}
    state = terminal.get("state")
    state = state if isinstance(state, dict) else {}
    raw_planner_memory = planner_evidence.get("development_memory")
    raw_planner_memory = (
        raw_planner_memory if isinstance(raw_planner_memory, dict) else {}
    )

    base_sha = task.get("base_sha")
    merge_sha = task.get("merge_commit")
    memory_pairs = _memory_pairs(memory)

    proof002_records = tuple(
        record for record in store.ledger.records if record.task_id == TASK_ID
    )
    reused_memory_ids = {memory_id for memory_id, _ in memory_pairs}
    preproof_records = tuple(
        record
        for record in store.ledger.records
        if record.memory_id in reused_memory_ids
    )
    planning_store = DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=preproof_records)
    )
    planning_records = {
        record.memory_id: record
        for record in planning_store.ledger.records
    }
    reused_records_match = bool(memory_pairs) and all(
        memory_id in planning_records
        and planning_records[memory_id].fingerprint() == fingerprint
        and planning_records[memory_id].repository == TARGET_REPOSITORY
        and planning_records[memory_id].source_sha == base_sha
        for memory_id, fingerprint in memory_pairs
    )

    bootstrap_feedback = bootstrap.get("durable_memory_feedback")
    bootstrap_feedback = (
        bootstrap_feedback if isinstance(bootstrap_feedback, dict) else {}
    )
    bootstrap_pair = (
        bootstrap_feedback.get("memory_id"),
        bootstrap_feedback.get("memory_fingerprint"),
    )
    bootstrap_reused = (
        isinstance(bootstrap_pair[0], str)
        and _sha256(bootstrap_pair[1])
        and bootstrap_pair in memory_pairs
    )

    result_rows = report.get("results")
    result_rows = result_rows if isinstance(result_rows, list) else []
    required_probes = {"offline-cli-smoke", "production-import-smoke"}
    result_ids = {
        row.get("probe_id")
        for row in result_rows
        if isinstance(row, dict)
    }

    expected_feedback = None
    try:
        raw_contract = RuntimeVerificationContract.from_dict(raw_contract_payload)
        raw_receipt = RuntimeVerificationReceipt.from_dict(raw_receipt_payload)
        raw_report = runtime_report_from_wrapper(raw_report_wrapper)
        expected_feedback = build_verified_runtime_feedback_record(
            contract=raw_contract,
            receipt=raw_receipt,
            report=raw_report,
            contract_path=RUNTIME_CONTRACT,
            receipt_path=RUNTIME_RECEIPT,
            report_path=RUNTIME_REPORT,
        )
    except (KeyError, TypeError, ValueError):
        raw_contract = None
        raw_receipt = None
        raw_report = None

    final_feedback_record = None
    if expected_feedback is not None:
        matches = [
            record
            for record in proof002_records
            if record.memory_id == expected_feedback.memory_id
        ]
        if len(matches) == 1:
            final_feedback_record = matches[0]

    graduation_store = None
    if expected_feedback is not None:
        graduation_store = DevelopmentMemoryStore(
            ledger=DevelopmentMemoryLedger(
                records=(
                    *planning_store.ledger.records,
                    expected_feedback,
                )
            )
        )

    live_records_by_id = {
        record.memory_id: record
        for record in store.ledger.records
    }
    graduation_records_preserved = (
        graduation_store is not None
        and all(
            record.memory_id in live_records_by_id
            and live_records_by_id[record.memory_id].canonical_dict()
            == record.canonical_dict()
            for record in graduation_store.ledger.records
        )
    )

    matching_target_records_before = [
        record
        for record in planning_store.ledger.records
        if record.repository == TARGET_REPOSITORY
    ]

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.5",
        "proof_identity": evidence.get("request_id") == REQUEST_ID
        and evidence.get("campaign_id") == CAMPAIGN_ID,
        "target_repository": evidence.get("target_repository") == TARGET_REPOSITORY,
        "goal_only_submission": evidence.get("human_authored_per_task_work_items")
        is False,
        "execution_provenance_clean": evidence.get("execution_provenance_clean")
        is True,
        "bootstrap_proof_bound": bootstrap.get("schema_version") == 1
        and bootstrap.get("version") == "v1.5-bootstrap"
        and bootstrap.get("request_id") == "v1.5-development-memory-proof-001"
        and bootstrap.get("campaign_id")
        == "v1.5-development-memory-campaign-001"
        and bootstrap.get("successor_request_id") == REQUEST_ID
        and bootstrap.get("graduation_eligible") is False
        and bootstrap.get("target_repository") == TARGET_REPOSITORY
        and bootstrap.get("runtime_verification", {}).get("status") == "VERIFIED"
        and bootstrap.get("runtime_verification", {}).get("source_sha") == base_sha,
        "planner_chain": _positive_int(planner.get("workflow_run"))
        and planner_evidence.get("workflow_run_id") == planner.get("workflow_run")
        and _positive_int(planner_evidence.get("workflow_run_id"))
        and planner.get("planning_only") is True
        and _sha256(planner.get("accepted_plan_fingerprint"))
        and planner.get("repository_source_sha") == base_sha,
        "planner_evidence_bound": planner_evidence.get("schema_version") == 1
        and planner_evidence.get("campaign_id") == CAMPAIGN_ID
        and planner_evidence.get("request", {}).get("request_id") == REQUEST_ID
        and planner_evidence.get("accepted_plan_fingerprint")
        == planner.get("accepted_plan_fingerprint")
        and planner_evidence.get("planning_only") is True
        and planner_evidence.get("repository_source_sha") == base_sha
        and raw_planner_memory == memory,
        "durable_store_is_planner_source": memory.get("used") is True
        and memory.get("authority") == "advisory-data-only"
        and memory.get("execution_authority") is False
        and memory.get("memory_may_expand_scope") is False
        and memory.get("memory_may_override_acceptance") is False
        and memory.get("source_evidence_path") == STORE_PATH
        and memory.get("source_evidence_fingerprint") == planning_store.fingerprint()
        and memory.get("repository") == TARGET_REPOSITORY
        and memory.get("current_source_sha") == base_sha
        and memory.get("extracted_record_count")
        == len(matching_target_records_before)
        and memory.get("retrieved_record_count") == len(memory_pairs),
        "exact_reused_record_fingerprints": reused_records_match,
        "bootstrap_feedback_reused": bootstrap_reused,
        "external_task_chain": task.get("task_id") == TASK_ID
        and _sha40(base_sha)
        and _positive_int(task.get("zero_touch_run"))
        and _positive_int(task.get("jules_cycle_run"))
        and _positive_int(task.get("pull_request"))
        and _positive_int(task.get("ci_run"))
        and _positive_int(task.get("remote_gate_run"))
        and _positive_int(task.get("remote_monitor_run"))
        and _sha40(task.get("head_sha"))
        and _sha40(merge_sha)
        and task.get("changed_paths") == ["tests/test_models.py"],
        "runtime_raw_evidence_bound": raw_contract_payload == contract
        and raw_receipt_payload == receipt
        and raw_report_wrapper.get("report") == report
        and raw_report_wrapper.get("report_fingerprint")
        == runtime.get("report_fingerprint"),
        "runtime_workflow": _positive_int(runtime.get("workflow_run"))
        and runtime.get("trigger_source") == "repository_dispatch"
        and runtime.get("manual_workflow_dispatch") is False,
        "runtime_exact_merge_sha": contract.get("schema_version") == 1
        and contract.get("target_repository") == TARGET_REPOSITORY
        and contract.get("source_sha") == merge_sha
        and contract.get("environment") == "repository"
        and set(contract.get("required_probe_ids", [])) == required_probes
        and contract.get("max_attempts") == 2
        and contract.get("timeout_seconds") == 300
        and receipt.get("schema_version") == 1
        and receipt.get("task_id") == TASK_ID
        and receipt.get("status") == "VERIFIED"
        and receipt.get("source_sha") == merge_sha
        and receipt.get("target_repository") == TARGET_REPOSITORY
        and receipt.get("dispatch_count") == 1
        and report.get("schema_version") == 1
        and report.get("disposition") == "VERIFIED"
        and report.get("source_sha") == merge_sha
        and set(result_ids) == required_probes
        and len(result_rows) == 2
        and all(
            isinstance(row, dict)
            and row.get("status") == "PASS"
            and row.get("source_sha") == merge_sha
            and row.get("attempt") == 1
            for row in result_rows
        )
        and {
            row.get("probe_id"): row.get("detail_code")
            for row in result_rows
            if isinstance(row, dict)
        }
        == {
            "offline-cli-smoke": "offline-cli-pass",
            "production-import-smoke": "production-import-pass",
        },
        "runtime_workspace_bound": runtime.get("workspace_source_sha") == merge_sha
        and _sha256(runtime.get("dependency_fingerprint"))
        and runtime.get("recovery_triggered") is False
        and runtime.get("human_wait_triggered") is False,
        "runtime_feedback_added": feedback.get("state") in {"ADDED", "UNCHANGED"}
        and feedback.get("memory_kind") == "VERIFIED_OUTCOME"
        and feedback.get("repository") == TARGET_REPOSITORY
        and feedback.get("source_sha") == merge_sha
        and graduation_store is not None
        and _sha256(feedback.get("store_fingerprint"))
        and feedback.get("store_fingerprint") == graduation_store.fingerprint()
        and feedback.get("record_count") == len(graduation_store.ledger.records),
        "append_only_store_preserves_graduation_records": graduation_records_preserved,
        "final_feedback_record_bound": expected_feedback is not None
        and final_feedback_record is not None
        and final_feedback_record.canonical_dict()
        == expected_feedback.canonical_dict()
        and len(proof002_records) == 1,
        "campaign_completed": campaign.get("campaign_id") == CAMPAIGN_ID
        and campaign.get("status") == "COMPLETED"
        and campaign.get("task_ids") == [TASK_ID]
        and campaign.get("completed_task_ids") == [TASK_ID],
        "state_terminal": state.get("status") == "READY"
        and state.get("current_task_id") is None
        and state.get("failed_task_ids") == [],
        "no_manual_campaign_progress": evidence.get(
            "manual_campaign_progress_after_goal_submission"
        )
        is False,
        "required_ci_proofs": not missing_proofs,
    }

    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "bootstrap_memory_id": bootstrap_pair[0],
        "planning_store_fingerprint": planning_store.fingerprint(),
        "final_store_fingerprint": (
            graduation_store.fingerprint()
            if graduation_store is not None
            else None
        ),
        "live_store_fingerprint": store.fingerprint(),
        "reused_memory_count": len(memory_pairs),
        "v1_5_development_memory_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_5_development_memory_graduated"]:
        raise SystemExit(1)
