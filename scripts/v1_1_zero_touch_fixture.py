from __future__ import annotations
import json
from ade.accepted_plan import AcceptedPlan
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.plan_compiler import compile_plan

GOAL="Add a small zero-touch campaign marker utility and prove it with focused tests."
PLAN=DevelopmentPlan(
    GOAL,
    (
        PlannedTask(
            "v1-1-zero-touch-001",
            "Add zero-touch campaign marker",
            "Goal: "+GOAL+"\nOutcome: Add a pure zero_touch_campaign_marker helper returning a deterministic dictionary with campaign_id, mode, and started flag.",
            (),
            ("src/ade/zero_touch_campaign.py",),
            ("helper is pure and deterministic","empty campaign_id or mode is rejected"),
        ),
        PlannedTask(
            "v1-1-zero-touch-002",
            "Prove zero-touch campaign marker",
            "Goal: "+GOAL+"\nOutcome: Add focused stdlib unit tests for zero_touch_campaign_marker covering deterministic output and invalid inputs.",
            ("v1-1-zero-touch-001",),
            ("tests/test_zero_touch_campaign.py",),
            ("focused tests cover valid deterministic output","invalid campaign_id and mode behavior is tested","full repository tests remain green"),
        ),
    ),
    (
        "destructive or irreversible operation",
        "credential or secret access",
        "externally consequential side effect",
    ),
)

def build_fixture()->dict:
    accepted=AcceptedPlan.accept(PLAN)
    campaign,graph=compile_plan(accepted.plan,campaign_id="v1.1-zero-touch-proof-001")
    campaign_payload=campaign.to_dict()
    campaign_payload["status"]="RUNNING"
    graph_payload=graph.to_dict()
    graph_payload["tasks"][0]["status"]="RUNNING"
    return {
        "accepted":accepted.to_dict(),
        "campaign":campaign_payload,
        "graph":graph_payload,
        "cycle_task":graph_payload["tasks"][0]["task"],
    }

if __name__=="__main__":
    print(json.dumps(build_fixture(),indent=2,sort_keys=True))
