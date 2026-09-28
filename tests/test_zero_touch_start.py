from __future__ import annotations

import copy
import unittest
from datetime import UTC, datetime, timedelta

from ade.accepted_plan import AcceptedPlan
from ade.campaign import CampaignStatus
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.plan_compiler import compile_plan
from ade.zero_touch_start import StartDisposition, evaluate_zero_touch_start


NOW = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)


def fixture() -> dict:
    plan = DevelopmentPlan(
        "Ship zero-touch proof",
        (
            PlannedTask(
                "zt-001",
                "Add helper",
                "Goal: Ship zero-touch proof\nOutcome: Add helper",
                (),
                ("src/ade/helper.py",),
                ("helper is deterministic",),
            ),
            PlannedTask(
                "zt-002",
                "Add tests",
                "Goal: Ship zero-touch proof\nOutcome: Add tests",
                ("zt-001",),
                ("tests/test_helper.py",),
                ("tests pass",),
            ),
        ),
    )
    accepted = AcceptedPlan.accept(plan)
    campaign, graph = compile_plan(plan, campaign_id="v1-1-proof")
    campaign_payload = campaign.to_dict()
    campaign_payload["status"] = CampaignStatus.RUNNING.value
    graph_payload = graph.to_dict()
    graph_payload["tasks"][0]["status"] = "RUNNING"
    first_task = copy.deepcopy(graph_payload["tasks"][0]["task"])
    state = {
        "schema_version": 1,
        "project_id": "ade-test",
        "status": "READY",
        "iteration": 0,
        "current_task_id": "zt-001",
        "completed_task_ids": [],
        "failed_task_ids": [],
        "provider": "jules",
        "updated_at": None,
        "metadata": {"campaign_id": "v1-1-proof"},
    }
    return {
        "accepted_plan_payload": accepted.to_dict(),
        "campaign_payload": campaign_payload,
        "graph_payload": graph_payload,
        "state_payload": state,
        "cycle_task_payload": first_task,
        "now": NOW,
    }


class ZeroTouchStartTests(unittest.TestCase):
    def test_eligible_bundle_dispatches(self) -> None:
        decision = evaluate_zero_touch_start(**fixture())
        self.assertEqual(decision.disposition, StartDisposition.DISPATCH)
        self.assertTrue(decision.should_dispatch)
        self.assertEqual(decision.task_id, "zt-001")

    def test_recent_receipt_suppresses_duplicate_event_replay(self) -> None:
        args = fixture()
        args["receipt_payload"] = {
            "schema_version": 1,
            "status": "DISPATCHED",
            "campaign_id": "v1-1-proof",
            "task_id": "zt-001",
            "plan_fingerprint": args["accepted_plan_payload"]["fingerprint"],
            "dispatched_at": (NOW - timedelta(minutes=2)).isoformat(),
            "dispatch_count": 1,
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.NOOP)
        self.assertEqual(decision.reason, "recent-zero-touch-dispatch")

    def test_stale_receipt_allows_watchdog_retry(self) -> None:
        args = fixture()
        args["receipt_payload"] = {
            "schema_version": 1,
            "status": "DISPATCHED",
            "campaign_id": "v1-1-proof",
            "task_id": "zt-001",
            "plan_fingerprint": args["accepted_plan_payload"]["fingerprint"],
            "dispatched_at": (NOW - timedelta(minutes=11)).isoformat(),
            "dispatch_count": 1,
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.DISPATCH)

    def test_live_lease_suppresses_provider_duplicate(self) -> None:
        args = fixture()
        args["lease_payload"] = {
            "schema_version": 1,
            "task_id": "zt-001",
            "owner_id": "github-actions:1:1",
            "attempt": 1,
            "acquired_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(minutes=49)).isoformat(),
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.NOOP)
        self.assertEqual(decision.reason, "active-execution-lease")

    def test_different_live_lease_blocks_start(self) -> None:
        args = fixture()
        args["lease_payload"] = {
            "schema_version": 1,
            "task_id": "other-task",
            "owner_id": "github-actions:2:1",
            "attempt": 1,
            "acquired_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(minutes=49)).isoformat(),
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.BLOCKED)

    def test_completed_previous_task_checkpoint_allows_new_task_handoff(self) -> None:
        args = fixture()
        args["lease_payload"] = {
            "schema_version": 1,
            "task_id": "previous-task",
            "owner_id": "github-actions:2:1",
            "attempt": 1,
            "acquired_at": (NOW - timedelta(minutes=1)).isoformat(),
            "expires_at": (NOW + timedelta(minutes=49)).isoformat(),
        }
        args["checkpoint_payload"] = {
            "task_id": "previous-task",
            "state": "COMPLETED",
            "attempt": 0,
            "replan_count": 0,
            "provider_session_id": "completed-previous-session",
            "last_failure_kind": None,
            "last_error": None,
            "resume_after": None,
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.DISPATCH)
        self.assertEqual(decision.reason, "eligible-zero-touch-start")

    def test_human_wait_never_dispatches(self) -> None:
        args = fixture()
        args["state_payload"]["status"] = "HUMAN_WAIT"
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.HUMAN_WAIT)

    def test_recovery_checkpoint_owns_existing_work(self) -> None:
        args = fixture()
        args["checkpoint_payload"] = {
            "task_id": "zt-001",
            "state": "RUNNING",
            "attempt": 0,
            "replan_count": 0,
            "provider_session_id": "existing-session",
            "last_failure_kind": None,
            "last_error": None,
            "resume_after": None,
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.RECOVERING)
        self.assertEqual(decision.reason, "checkpoint-recovery-owned")

    def test_completed_checkpoint_never_restarts_provider_work(self) -> None:
        args = fixture()
        args["checkpoint_payload"] = {
            "task_id": "zt-001",
            "state": "COMPLETED",
            "attempt": 0,
            "replan_count": 0,
            "provider_session_id": "completed-session",
            "last_failure_kind": None,
            "last_error": None,
            "resume_after": None,
        }
        decision = evaluate_zero_touch_start(**args)
        self.assertEqual(decision.disposition, StartDisposition.NOOP)
        self.assertEqual(decision.reason, "provider-work-completed")

    def test_plan_drift_is_rejected_before_dispatch(self) -> None:
        args = fixture()
        args["cycle_task_payload"]["title"] = "drifted"
        with self.assertRaisesRegex(ValueError, "cycle task"):
            evaluate_zero_touch_start(**args)

    def test_tampered_accepted_plan_is_rejected(self) -> None:
        args = fixture()
        args["accepted_plan_payload"]["plan"]["goal"] = "tampered"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            evaluate_zero_touch_start(**args)


if __name__ == "__main__":
    unittest.main()
