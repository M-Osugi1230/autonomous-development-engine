from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_EVIDENCE = ".autodev/campaign-evidence/v1.3-repository-intelligence-proof-001.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CI_PROOFS = (
    "Zero-Touch Start proof",
    "Execution lease duplicate-dispatch proof",
    "Autonomous Planner proof",
    "Autonomous Planner activation proof",
    "Autonomous Planner capacity retry proof",
    "Repository Intelligence proof",
    "Remote Repository Loop proof",
    "Mission Control observability proof",
    "Autonomous recovery fault proof",
    "Checkpoint restart proof",
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


def _task_evidence(task: object) -> bool:
    if not isinstance(task, dict):
        return False
    return (
        isinstance(task.get("task_id"), str)
        and bool(task["task_id"].strip())
        and _positive_int(task.get("jules_cycle_run"))
        and _positive_int(task.get("pull_request"))
        and _positive_int(task.get("ci_run"))
        and _positive_int(task.get("remote_gate_run"))
        and _positive_int(task.get("remote_monitor_run"))
        and _sha40(task.get("head_sha"))
        and _sha40(task.get("merge_commit"))
    )


def audit(
    root: Path,
    *,
    evidence_path: str = DEFAULT_EVIDENCE,
) -> dict[str, object]:
    evidence = _load(root, evidence_path)
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    repository_intelligence = evidence.get("repository_intelligence")
    repository_intelligence = (
        repository_intelligence
        if isinstance(repository_intelligence, dict)
        else {}
    )
    planner = evidence.get("planner")
    planner = planner if isinstance(planner, dict) else {}
    initial = evidence.get("initial_start")
    initial = initial if isinstance(initial, dict) else {}
    tasks = evidence.get("tasks")
    tasks = tasks if isinstance(tasks, list) else []
    snapshot = evidence.get("terminal_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}

    accepted = snapshot.get("accepted_plan")
    accepted = accepted if isinstance(accepted, dict) else {}
    campaign = snapshot.get("campaign")
    campaign = campaign if isinstance(campaign, dict) else {}
    graph = snapshot.get("task_graph")
    graph = graph if isinstance(graph, list) else []
    state = snapshot.get("state")
    state = state if isinstance(state, dict) else {}
    remote_receipt = snapshot.get("remote_execution_receipt")
    remote_receipt = remote_receipt if isinstance(remote_receipt, dict) else {}

    campaign_task_ids = campaign.get("task_ids")
    completed_task_ids = campaign.get("completed_task_ids")
    graph_ids = [
        node.get("task_id")
        for node in graph
        if isinstance(node, dict)
    ]

    grounded_paths = repository_intelligence.get("grounded_task_paths")
    grounded_paths = grounded_paths if isinstance(grounded_paths, list) else []

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.3",
        "proof_identity": (
            evidence.get("request_id") == "v1.3-repository-intelligence-proof-001"
            and evidence.get("campaign_id")
            == "v1.3-repository-intelligence-campaign-001"
        ),
        "target_repository": evidence.get("target_repository")
        == "M-Osugi1230/one-minute-thought-experiments",
        "goal_only_submission": evidence.get("human_authored_per_task_work_items") is False,
        "repository_snapshot": _sha40(repository_intelligence.get("source_sha"))
        and _sha256(repository_intelligence.get("snapshot_fingerprint"))
        and _sha256(repository_intelligence.get("context_fingerprint")),
        "bounded_content_intelligence": _sha256(
            repository_intelligence.get("content_summary_fingerprint")
        )
        and repository_intelligence.get("raw_source_persisted") is False,
        "relationship_intelligence": _sha256(
            repository_intelligence.get("relationship_graph_fingerprint")
        ),
        "impact_intelligence": _sha256(
            repository_intelligence.get("impact_analysis_fingerprint")
        )
        and repository_intelligence.get("impact_analysis_advisory_only") is True,
        "path_grounding": repository_intelligence.get("path_grounding_enforced") is True
        and len(grounded_paths) >= 2
        and all(
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and bool(item["path"].strip())
            and item.get("exists_in_snapshot") is True
            and item.get("declared_new") is False
            for item in grounded_paths
        ),
        "planner_boundary": planner.get("provider") == "jules"
        and planner.get("planning_only") is True
        and planner.get("plan_approved") is False
        and planner.get("provider_execution_boundary_crossed") is False
        and planner.get("proposal_mode") in {"structured", "derived-plan-steps"}
        and _positive_int(planner.get("workflow_run"))
        and _sha40(planner.get("source_sha")),
        "planner_multi_task": _positive_int(planner.get("task_count"))
        and planner["task_count"] >= 2,
        "accepted_fingerprint": isinstance(
            evidence.get("accepted_plan_fingerprint"), str
        )
        and bool(evidence["accepted_plan_fingerprint"].strip())
        and accepted.get("fingerprint") == evidence.get("accepted_plan_fingerprint")
        and accepted.get("status") == "ACCEPTED",
        "automatic_initial_start": initial.get("manual_workflow_dispatch") is False
        and initial.get("trigger_source") == "repository_dispatch"
        and _positive_int(initial.get("workflow_run")),
        "real_multi_task_evidence": len(tasks) >= 2
        and all(_task_evidence(task) for task in tasks),
        "no_manual_campaign_progress": evidence.get(
            "manual_campaign_progress_after_goal_submission"
        )
        is False,
        "campaign_completed": campaign.get("campaign_id") == evidence.get("campaign_id")
        and campaign.get("status") == "COMPLETED",
        "all_campaign_tasks_completed": isinstance(campaign_task_ids, list)
        and len(campaign_task_ids) >= 2
        and completed_task_ids == campaign_task_ids,
        "graph_completed": graph_ids == campaign_task_ids
        and len(graph) == len(campaign_task_ids or [])
        and all(
            isinstance(node, dict) and node.get("status") == "COMPLETED"
            for node in graph
        ),
        "state_terminal": state.get("current_task_id") is None
        and state.get("failed_task_ids") == []
        and state.get("completed_campaign_task_ids") == campaign_task_ids,
        "remote_receipt_terminal": remote_receipt.get("schema_version") == 1
        and remote_receipt.get("status") == "MERGED"
        and isinstance(campaign_task_ids, list)
        and bool(campaign_task_ids)
        and remote_receipt.get("task_id") == campaign_task_ids[-1],
        "terminal_source_sha": _sha40(snapshot.get("source_sha")),
        "terminal_evidence": evidence.get("terminal_status") == "COMPLETED"
        and evidence.get("failed_tasks") == 0,
        "required_ci_proofs": not missing_proofs,
    }

    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "v1_3_repository_intelligence_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_3_repository_intelligence_graduated"]:
        raise SystemExit(1)
