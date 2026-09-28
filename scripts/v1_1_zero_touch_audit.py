from __future__ import annotations

import json
import re
from pathlib import Path

SHA40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CI_PROOFS = (
    "Zero-Touch Start proof",
    "Execution lease duplicate-dispatch proof",
    "Checkpoint restart proof",
    "Human decision boundary proof",
    "Autonomous recovery fault proof",
    "Mission Control observability proof",
)


def _load(root: Path, relative: str) -> dict:
    payload = json.loads((root / relative).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{relative} must contain a JSON object")
    return payload


def _task_evidence(task: object) -> bool:
    if not isinstance(task, dict):
        return False
    return (
        isinstance(task.get("task_id"), str)
        and bool(task["task_id"].strip())
        and type(task.get("pull_request")) is int
        and task["pull_request"] > 0
        and type(task.get("ci_run")) is int
        and task["ci_run"] > 0
        and isinstance(task.get("merge_commit"), str)
        and SHA40.fullmatch(task["merge_commit"]) is not None
    )


def audit(root: Path) -> dict[str, object]:
    evidence = _load(root, ".autodev/campaign-evidence/v1.1-zero-touch-proof-001.json")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/zero-touch-start.yml").read_text(encoding="utf-8")
    mission = (root / "src/ade/mission_control.py").read_text(encoding="utf-8")

    tasks = evidence.get("tasks", [])
    snapshot = evidence.get("terminal_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    accepted = snapshot.get("accepted_plan")
    campaign = snapshot.get("campaign")
    graph_tasks = snapshot.get("task_graph")
    state = snapshot.get("state")
    receipt = snapshot.get("zero_touch_receipt")
    source_sha = snapshot.get("source_sha")

    accepted = accepted if isinstance(accepted, dict) else {}
    campaign = campaign if isinstance(campaign, dict) else {}
    graph_tasks = graph_tasks if isinstance(graph_tasks, list) else []
    state = state if isinstance(state, dict) else {}
    receipt = receipt if isinstance(receipt, dict) else {}

    campaign_task_ids = campaign.get("task_ids")
    completed = campaign.get("completed_task_ids")
    snapshot_completed = state.get("completed_campaign_task_ids")
    missing_proofs = [name for name in REQUIRED_CI_PROOFS if name not in ci]

    checks = {
        "evidence_schema": evidence.get("schema_version") == 1
        and evidence.get("version") == "v1.1",
        "immutable_terminal_snapshot": isinstance(source_sha, str)
        and SHA40.fullmatch(source_sha) is not None,
        "accepted_plan_validated": accepted.get("status") == "ACCEPTED"
        and accepted.get("fingerprint") == evidence.get("accepted_plan_fingerprint"),
        "accepted_plan_task_ids": accepted.get("task_ids") == campaign_task_ids
        and isinstance(campaign_task_ids, list)
        and len(campaign_task_ids) == 2,
        "campaign_completed": campaign.get("campaign_id") == evidence.get("campaign_id")
        and campaign.get("status") == "COMPLETED",
        "campaign_all_tasks_completed": isinstance(completed, list)
        and completed == campaign_task_ids,
        "graph_completed": len(graph_tasks) == 2
        and [
            node.get("task_id")
            for node in graph_tasks
            if isinstance(node, dict)
        ] == campaign_task_ids
        and all(
            isinstance(node, dict) and node.get("status") == "COMPLETED"
            for node in graph_tasks
        ),
        "state_no_failed_tasks": state.get("failed_task_ids") == []
        and state.get("current_task_id") is None
        and snapshot_completed == campaign_task_ids,
        "real_two_task_evidence": isinstance(tasks, list)
        and len(tasks) == 2
        and all(_task_evidence(task) for task in tasks),
        "automatic_initial_start": evidence.get("manual_initial_workflow_dispatch") is False
        and isinstance(evidence.get("initial_start"), dict)
        and evidence["initial_start"].get("trigger_source") == "push"
        and type(evidence["initial_start"].get("workflow_run")) is int
        and evidence["initial_start"]["workflow_run"] > 0,
        "automatic_between_tasks": evidence.get("manual_dispatch_between_tasks") is False
        and isinstance(tasks, list)
        and len(tasks) == 2
        and type(tasks[1].get("dispatch_run")) is int
        and tasks[1]["dispatch_run"] > 0,
        "receipt_reconciled": receipt.get("schema_version") == 1
        and receipt.get("status") == "DISPATCHED"
        and receipt.get("campaign_id") == evidence.get("campaign_id")
        and receipt.get("plan_fingerprint") == evidence.get("accepted_plan_fingerprint")
        and receipt.get("source") == "push"
        and receipt.get("dispatch_count") == 1
        and receipt.get("run_id") == str(evidence["initial_start"].get("workflow_run")),
        "watchdog_declared": "schedule:" in workflow and "*/15 * * * *" in workflow,
        "mission_control_receipt": "zero-touch-start.json" in mission,
        "required_ci_proofs": not missing_proofs,
        "terminal_evidence": evidence.get("terminal_status") == "COMPLETED"
        and evidence.get("failed_tasks") == 0,
    }
    return {
        "schema_version": 1,
        "checks": checks,
        "missing_proofs": missing_proofs,
        "v1_1_zero_touch_graduated": all(checks.values()),
    }


if __name__ == "__main__":
    result = audit(Path("."))
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["v1_1_zero_touch_graduated"]:
        raise SystemExit(1)
