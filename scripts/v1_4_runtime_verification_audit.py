from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_EVIDENCE = ".autodev/campaign-evidence/v1.4-runtime-verification-proof-001.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CI_PROOFS = (
    "Zero-Touch Start proof",
    "Execution lease duplicate-dispatch proof",
    "Autonomous Planner proof",
    "Repository Intelligence proof",
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


def audit(
    root: Path,
    *,
    evidence_path: str = DEFAULT_EVIDENCE,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    task = evidence.get("task")
    task = task if isinstance(task, dict) else {}
    runtime = evidence.get("runtime_verification")
    runtime = runtime if isinstance(runtime, dict) else {}
    contract = runtime.get("contract")
    contract = contract if isinstance(contract, dict) else {}
    receipt = runtime.get("receipt")
    receipt = receipt if isinstance(receipt, dict) else {}
    target = runtime.get("target")
    target = target if isinstance(target, dict) else {}
    target_evidence = target.get("evidence")
    target_evidence = target_evidence if isinstance(target_evidence, dict) else {}
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

    merge_sha = task.get("merge_commit")
    required_probes = {"offline-cli-smoke", "production-import-smoke"}
    result_ids = {
        result.get("probe_id")
        for result in results
        if isinstance(result, dict)
    }

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.4",
        "proof_identity": evidence.get("request_id")
        == "v1.4-runtime-verification-proof-001"
        and evidence.get("campaign_id")
        == "v1.4-runtime-verification-campaign-001",
        "target_repository": evidence.get("target_repository")
        == "M-Osugi1230/one-minute-thought-experiments",
        "goal_only_submission": evidence.get("human_authored_per_task_work_items") is False,
        "external_task_chain": isinstance(task.get("task_id"), str)
        and bool(task["task_id"].strip())
        and _positive_int(task.get("planner_workflow_run"))
        and _positive_int(task.get("zero_touch_run"))
        and _positive_int(task.get("jules_cycle_run"))
        and _positive_int(task.get("pull_request"))
        and _positive_int(task.get("ci_run"))
        and _positive_int(task.get("remote_gate_run"))
        and _positive_int(task.get("remote_monitor_run"))
        and _sha40(task.get("head_sha"))
        and _sha40(merge_sha),
        "runtime_workflow": _positive_int(runtime.get("workflow_run"))
        and runtime.get("trigger_source") == "repository_dispatch"
        and runtime.get("manual_workflow_dispatch") is False,
        "contract_exact_merge_sha": contract.get("schema_version") == 1
        and contract.get("target_repository") == evidence.get("target_repository")
        and contract.get("source_sha") == merge_sha
        and contract.get("environment") == "repository"
        and set(contract.get("required_probe_ids", [])) == required_probes
        and contract.get("max_attempts") == 2
        and contract.get("timeout_seconds") == 300,
        "receipt_verified": receipt.get("schema_version") == 1
        and receipt.get("status") == "VERIFIED"
        and receipt.get("source_sha") == merge_sha
        and receipt.get("target_repository") == evidence.get("target_repository")
        and receipt.get("dispatch_count") == 1
        and _sha256(receipt.get("contract_fingerprint"))
        and _sha256(receipt.get("registry_fingerprint"))
        and _sha256(receipt.get("policy_fingerprint")),
        "repository_runtime_target": target_evidence.get("schema_version") == 1
        and target_evidence.get("kind") == "repository"
        and target_evidence.get("environment") == "repository"
        and target_evidence.get("source_sha") == merge_sha
        and target_evidence.get("target_repository") == evidence.get("target_repository")
        and target_evidence.get("deployment_id") is None
        and target_evidence.get("provenance_id") == "trusted-merge-sha-v1",
        "real_runtime_report": report.get("schema_version") == 1
        and report.get("disposition") == "VERIFIED"
        and report.get("source_sha") == merge_sha
        and set(result_ids) == required_probes
        and len(results) == 2
        and all(
            isinstance(result, dict)
            and result.get("status") == "PASS"
            and result.get("source_sha") == merge_sha
            and type(result.get("attempt")) is int
            and 1 <= result["attempt"] <= 2
            for result in results
        ),
        "real_probe_detail_codes": {
            result.get("probe_id"): result.get("detail_code")
            for result in results
            if isinstance(result, dict)
        }
        == {
            "offline-cli-smoke": "offline-cli-pass",
            "production-import-smoke": "production-import-pass",
        },
        "workspace_source_binding": runtime.get("workspace_source_sha") == merge_sha
        and _sha256(runtime.get("dependency_fingerprint")),
        "no_runtime_recovery": runtime.get("recovery_triggered") is False
        and runtime.get("human_wait_triggered") is False,
        "campaign_completed": campaign.get("campaign_id") == evidence.get("campaign_id")
        and campaign.get("status") == "COMPLETED"
        and campaign.get("completed_task_ids") == campaign.get("task_ids"),
        "state_terminal": state.get("current_task_id") is None
        and state.get("failed_task_ids") == []
        and state.get("status") == "READY",
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
        "v1_4_runtime_verification_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_4_runtime_verification_graduated"]:
        raise SystemExit(1)
