from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.accepted_plan import AcceptedPlan
from ade.campaign import CampaignStatus
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.plan_compiler import compile_plan
from ade.zero_touch_start import StartDisposition, evaluate_zero_touch_start


def _fixture(now: datetime) -> dict:
    plan = DevelopmentPlan(
        "Prove zero-touch start",
        (
            PlannedTask(
                "proof-001",
                "Proof task",
                "Goal: Prove zero-touch start\nOutcome: Add proof",
                (),
                ("src/ade/proof.py",),
                ("proof is deterministic",),
            ),
        ),
    )
    accepted = AcceptedPlan.accept(plan)
    campaign, graph = compile_plan(plan, campaign_id="zero-touch-proof")
    campaign_payload = campaign.to_dict()
    campaign_payload["status"] = CampaignStatus.RUNNING.value
    graph_payload = graph.to_dict()
    graph_payload["tasks"][0]["status"] = "RUNNING"
    return {
        "accepted_plan_payload": accepted.to_dict(),
        "campaign_payload": campaign_payload,
        "graph_payload": graph_payload,
        "state_payload": {
            "schema_version": 1,
            "project_id": "proof",
            "status": "READY",
            "iteration": 0,
            "current_task_id": "proof-001",
            "completed_task_ids": [],
            "failed_task_ids": [],
            "provider": "jules",
            "updated_at": None,
            "metadata": {"campaign_id": "zero-touch-proof"},
        },
        "cycle_task_payload": copy.deepcopy(graph_payload["tasks"][0]["task"]),
        "now": now,
    }


def main() -> int:
    now = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)
    base = _fixture(now)
    eligible = evaluate_zero_touch_start(**base)
    assert eligible.disposition is StartDisposition.DISPATCH

    recent = dict(base)
    recent["receipt_payload"] = {
        "schema_version": 1,
        "status": "DISPATCHED",
        "campaign_id": eligible.campaign_id,
        "task_id": eligible.task_id,
        "plan_fingerprint": eligible.plan_fingerprint,
        "dispatched_at": (now - timedelta(minutes=1)).isoformat(),
        "dispatch_count": 1,
    }
    assert evaluate_zero_touch_start(**recent).reason == "recent-zero-touch-dispatch"

    lease = dict(base)
    lease["lease_payload"] = {
        "schema_version": 1,
        "task_id": "proof-001",
        "owner_id": "run:1",
        "attempt": 1,
        "acquired_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=49)).isoformat(),
    }
    assert evaluate_zero_touch_start(**lease).reason == "active-execution-lease"

    human = copy.deepcopy(base)
    human["state_payload"]["status"] = "HUMAN_WAIT"
    assert evaluate_zero_touch_start(**human).disposition is StartDisposition.HUMAN_WAIT

    recovery = dict(base)
    recovery["checkpoint_payload"] = {
        "task_id": "proof-001",
        "state": "RUNNING",
        "attempt": 0,
        "replan_count": 0,
        "provider_session_id": "existing-session",
        "last_failure_kind": None,
        "last_error": None,
        "resume_after": None,
    }
    assert evaluate_zero_touch_start(**recovery).disposition is StartDisposition.RECOVERING

    stale = dict(base)
    stale["receipt_payload"] = {
        "schema_version": 1,
        "status": "DISPATCHED",
        "campaign_id": eligible.campaign_id,
        "task_id": eligible.task_id,
        "plan_fingerprint": eligible.plan_fingerprint,
        "dispatched_at": (now - timedelta(minutes=11)).isoformat(),
        "dispatch_count": 1,
    }
    assert evaluate_zero_touch_start(**stale).disposition is StartDisposition.DISPATCH

    print(json.dumps({
        "ok": True,
        "accepted_plan_required": True,
        "automatic_dispatch_eligible": True,
        "duplicate_receipt_suppressed": True,
        "live_lease_suppressed": True,
        "human_wait_blocked": True,
        "recovery_owned": True,
        "stale_watchdog_retry": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
