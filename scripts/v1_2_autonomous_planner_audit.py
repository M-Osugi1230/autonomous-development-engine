from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEFAULT_EVIDENCE = ".autodev/campaign-evidence/v1.2-autonomous-planner-proof-005.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CI_PROOFS = (
    "Zero-Touch Start proof",
    "Execution lease duplicate-dispatch proof",
    "Autonomous Planner proof",
    "Jules Planner Adapter proof",
    "Autonomous Planner activation proof",
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
    zero_touch = (root / ".github/workflows/zero-touch-start.yml").read_text(
        encoding="utf-8"
    )
    remote_monitor = (root / ".github/workflows/remote-pr-monitor.yml").read_text(
        encoding="utf-8"
    )
    resume = (root / ".github/workflows/ade-resume.yml").read_text(encoding="utf-8")

    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    planner = evidence.get("planner")
    planner = planner if isinstance(planner, dict) else {}
    initial = evidence.get("initial_start")
    initial = initial if isinstance(initial, dict) else {}
    quota = evidence.get("quota_resume")
    quota = quota if isinstance(quota, dict) else {}
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

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.2",
        "proof_identity": evidence.get("request_id") == "v1.2-external-goal-proof-005"
        and evidence.get("campaign_id") == "v1.2-external-goal-campaign-005",
        "target_repository": evidence.get("target_repository")
        == "M-Osugi1230/one-minute-thought-experiments",
        "goal_only_submission": evidence.get("human_authored_per_task_work_items") is False,
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
        "explicit_zero_touch_handoff": "ade_zero_touch_start" in zero_touch,
        "explicit_remote_monitor_handoff": "ade_remote_pr_monitor" in remote_monitor,
        "quota_resume_safe": (
            quota.get("observed") is False
            and quota.get("resume_mode") == "not-needed"
        )
        or (
            quota.get("observed") is True
            and quota.get("manual_resume") is False
            and isinstance(quota.get("resume_after"), str)
            and bool(quota["resume_after"].strip())
            and quota.get("external_target_preserved") is True
            and quota.get("execution_lease_reclaimed") is True
            and _positive_int(quota.get("resume_run"))
        ),
        "resume_watchdog": 'cron: "*/15 * * * *"' in resume,
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
        and remote_receipt.get("task_id") == campaign_task_ids[-1]
        if isinstance(campaign_task_ids, list) and campaign_task_ids
        else False,
        "terminal_source_sha": _sha40(snapshot.get("source_sha")),
        "terminal_evidence": evidence.get("terminal_status") == "COMPLETED"
        and evidence.get("failed_tasks") == 0,
        "required_ci_proofs": not missing_proofs,
    }

    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "v1_2_autonomous_planner_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_2_autonomous_planner_graduated"]:
        raise SystemExit(1)
