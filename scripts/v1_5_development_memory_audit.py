from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ade.development_memory_extraction import evidence_fingerprint
from ade.development_memory_planning import build_planning_memory_bundle
from ade.development_memory_store import DevelopmentMemoryStore


DEFAULT_EVIDENCE = ".autodev/campaign-evidence/v1.5-development-memory-proof-001.json"
STORE_PATH = ".autodev/development-memory.json"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_MEMORY_EVIDENCE = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-003.json"
PLANNER_EVIDENCE = ".autodev/planner-evidence/v1.5-development-memory-proof-001.json"
RUNTIME_CONTRACT = ".autodev/runtime-verification/v15mem1-001/contract.json"
RUNTIME_RECEIPT = ".autodev/runtime-verification/v15mem1-001/receipt.json"
RUNTIME_REPORT = ".autodev/runtime-verification/v15mem1-001/report.json"
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


def _fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit(
    root: Path,
    *,
    evidence_path: str = DEFAULT_EVIDENCE,
    store_path: str = STORE_PATH,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    planner_evidence = _load(root, PLANNER_EVIDENCE)
    source_memory_evidence = _load(root, SOURCE_MEMORY_EVIDENCE)
    raw_runtime_contract = _load(root, RUNTIME_CONTRACT)
    raw_runtime_receipt = _load(root, RUNTIME_RECEIPT)
    raw_runtime_report_wrapper = _load(root, RUNTIME_REPORT)
    raw_runtime_report = raw_runtime_report_wrapper.get("report")
    raw_runtime_report = (
        raw_runtime_report if isinstance(raw_runtime_report, dict) else {}
    )
    store_payload = _load(root, store_path)
    store = DevelopmentMemoryStore.from_dict(store_payload)
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
    feedback = runtime.get("development_memory_feedback")
    feedback = feedback if isinstance(feedback, dict) else {}
    contract = runtime.get("contract")
    contract = contract if isinstance(contract, dict) else {}
    receipt = runtime.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    report = runtime.get("report")
    report = report if isinstance(report, dict) else {}
    results = report.get("results")
    results = results if isinstance(results, list) else []
    terminal = evidence.get("terminal_snapshot")
    terminal = terminal if isinstance(terminal, dict) else {}
    campaign = terminal.get("campaign")
    campaign = campaign if isinstance(campaign, dict) else {}
    state = terminal.get("state")
    state = state if isinstance(state, dict) else {}

    base_sha = task.get("base_sha")
    merge_sha = task.get("merge_commit")
    rebuilt_memory = {}
    if _sha40(base_sha):
        rebuilt_bundle = build_planning_memory_bundle(
            evidence_path=SOURCE_MEMORY_EVIDENCE,
            evidence_payload=source_memory_evidence,
            repository=TARGET_REPOSITORY,
            current_source_sha=base_sha,
        )
        rebuilt_memory = rebuilt_bundle.evidence_dict()
    required_probes = {"offline-cli-smoke", "production-import-smoke"}
    result_ids = {
        row.get("probe_id")
        for row in results
        if isinstance(row, dict)
    }

    memory_ids = memory.get("memory_ids")
    memory_ids = memory_ids if isinstance(memory_ids, list) else []
    raw_planner_memory = planner_evidence.get("development_memory")
    raw_planner_memory = (
        raw_planner_memory if isinstance(raw_planner_memory, dict) else {}
    )
    matching_feedback = [
        record
        for record in store.ledger.records
        if record.memory_id == feedback.get("memory_id")
    ]
    store_record = matching_feedback[0] if len(matching_feedback) == 1 else None

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.5",
        "proof_identity": evidence.get("request_id")
        == "v1.5-development-memory-proof-001"
        and evidence.get("campaign_id")
        == "v1.5-development-memory-campaign-001",
        "target_repository": evidence.get("target_repository") == TARGET_REPOSITORY,
        "goal_only_submission": evidence.get("human_authored_per_task_work_items") is False,
        "execution_provenance_clean": evidence.get("execution_provenance_clean") is True,
        "planner_chain": _positive_int(planner.get("workflow_run"))
        and planner.get("planning_only") is True
        and _sha256(planner.get("accepted_plan_fingerprint"))
        and planner.get("repository_source_sha") == base_sha,
        "planner_evidence_bound": planner_evidence.get("schema_version") == 1
        and planner_evidence.get("campaign_id") == evidence.get("campaign_id")
        and planner_evidence.get("accepted_plan_fingerprint")
        == planner.get("accepted_plan_fingerprint")
        and planner_evidence.get("planning_only") is True
        and planner_evidence.get("repository_source_sha") == base_sha
        and raw_planner_memory == memory,
        "source_memory_evidence_integrity": evidence_fingerprint(
            source_memory_evidence
        )
        == memory.get("source_evidence_fingerprint")
        and memory.get("source_evidence_path") == SOURCE_MEMORY_EVIDENCE,
        "memory_reuse_reproducible": bool(rebuilt_memory)
        and rebuilt_memory == memory
        and rebuilt_memory == raw_planner_memory,
        "memory_reused": memory.get("used") is True
        and memory.get("authority") == "advisory-data-only"
        and memory.get("execution_authority") is False
        and memory.get("memory_may_expand_scope") is False
        and memory.get("memory_may_override_acceptance") is False
        and memory.get("source_evidence_path") == SOURCE_MEMORY_EVIDENCE
        and _sha256(memory.get("source_evidence_fingerprint"))
        and _sha256(memory.get("resolution_fingerprint"))
        and _sha256(memory.get("retrieval_fingerprint"))
        and _sha256(memory.get("context_fingerprint"))
        and _positive_int(memory.get("extracted_record_count"))
        and _positive_int(memory.get("retrieved_record_count"))
        and len(memory_ids) == memory.get("retrieved_record_count")
        and all(isinstance(item, str) and item.startswith("mem-") for item in memory_ids)
        and memory.get("current_source_sha") == base_sha
        and memory.get("repository") == TARGET_REPOSITORY,
        "external_task_chain": task.get("task_id") == "v15mem1-001"
        and _positive_int(task.get("zero_touch_run"))
        and _positive_int(task.get("jules_cycle_run"))
        and _positive_int(task.get("pull_request"))
        and _positive_int(task.get("ci_run"))
        and _positive_int(task.get("remote_gate_run"))
        and _positive_int(task.get("remote_monitor_run"))
        and _sha40(base_sha)
        and _sha40(task.get("head_sha"))
        and _sha40(merge_sha)
        and task.get("changed_paths") == ["tests/test_models.py"],
        "runtime_raw_evidence_bound": raw_runtime_contract == contract
        and raw_runtime_receipt == receipt
        and raw_runtime_report == report
        and raw_runtime_report_wrapper.get("report_fingerprint")
        == runtime.get("report_fingerprint"),
        "runtime_workflow": _positive_int(runtime.get("workflow_run"))
        and runtime.get("trigger_source") == "repository_dispatch"
        and runtime.get("manual_workflow_dispatch") is False,
        "runtime_exact_merge_sha": contract.get("schema_version") == 1
        and contract.get("target_repository") == TARGET_REPOSITORY
        and contract.get("source_sha") == merge_sha
        and set(contract.get("required_probe_ids", [])) == required_probes
        and receipt.get("status") == "VERIFIED"
        and receipt.get("source_sha") == merge_sha
        and receipt.get("dispatch_count") == 1
        and report.get("disposition") == "VERIFIED"
        and report.get("source_sha") == merge_sha
        and set(result_ids) == required_probes
        and len(results) == 2
        and all(
            isinstance(row, dict)
            and row.get("status") == "PASS"
            and row.get("source_sha") == merge_sha
            and type(row.get("attempt")) is int
            and 1 <= row["attempt"] <= 2
            for row in results
        )
        and runtime.get("workspace_source_sha") == merge_sha
        and runtime.get("recovery_triggered") is False
        and runtime.get("human_wait_triggered") is False,
        "runtime_memory_feedback": feedback.get("state") == "ADDED"
        and isinstance(feedback.get("memory_id"), str)
        and feedback.get("memory_id", "").startswith("mem-")
        and feedback.get("memory_kind") == "VERIFIED_OUTCOME"
        and feedback.get("repository") == TARGET_REPOSITORY
        and feedback.get("source_sha") == merge_sha
        and _sha256(feedback.get("store_fingerprint"))
        and feedback.get("store_fingerprint") == store.fingerprint()
        and feedback.get("record_count") == len(store.ledger.records)
        and _positive_int(feedback.get("record_count")),
        "durable_store_feedback_record": store_record is not None
        and store_record.repository == TARGET_REPOSITORY
        and store_record.source_sha == merge_sha
        and store_record.task_id == "v15mem1-001"
        and set(store_record.tags) == {"feedback", "runtime", "verified"}
        and store_record.evidence_paths
        == (
            ".autodev/runtime-verification/v15mem1-001/contract.json",
            ".autodev/runtime-verification/v15mem1-001/receipt.json",
            ".autodev/runtime-verification/v15mem1-001/report.json",
        )
        and _sha256(runtime.get("report_fingerprint"))
        and store_record.evidence_fingerprints
        == (
            raw_runtime_receipt.get("contract_fingerprint"),
            _fingerprint(raw_runtime_receipt),
            raw_runtime_report_wrapper.get("report_fingerprint"),
        ),
        "campaign_completed": campaign.get("campaign_id")
        == "v1.5-development-memory-campaign-001"
        and campaign.get("status") == "COMPLETED"
        and campaign.get("completed_task_ids") == campaign.get("task_ids"),
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
        "memory_store_fingerprint": store.fingerprint(),
        "v1_5_development_memory_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_5_development_memory_graduated"]:
        raise SystemExit(1)
