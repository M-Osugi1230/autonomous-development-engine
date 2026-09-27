from __future__ import annotations
import json
from ade.accepted_plan import AcceptedPlan
from ade.goal_planner import GoalWorkItem, plan_goal
from ade.plan_compiler import compile_plan

GOAL="Add a small graduation metadata utility, prove its deterministic summary, and document its public behavior in code."
ITEMS=(
 GoalWorkItem("Add graduation metadata model","Add a pure graduation_metadata helper returning a deterministic dictionary for version, status, and completed phase count.",("src/ade/graduation.py",),("helper is pure and deterministic","invalid empty version or status is rejected")),
 GoalWorkItem("Prove graduation metadata","Add focused stdlib tests for the graduation_metadata helper including valid and invalid inputs.",("tests/test_graduation.py",),("focused tests cover deterministic output","invalid input behavior is tested"),(1,)),
 GoalWorkItem("Add graduation summary helper","Extend the graduation module with a pure graduation_summary helper that formats the validated metadata into one stable human-readable line.",("src/ade/graduation.py",),("summary output is deterministic","existing graduation metadata behavior remains unchanged"),(1,2)),
)

def build():
    plan=plan_goal(GOAL,ITEMS,id_prefix="phase17-final")
    accepted=AcceptedPlan.accept(plan)
    campaign,graph=compile_plan(plan,campaign_id="phase17-production-graduation-001")
    return {"accepted":accepted.to_dict(),"campaign":campaign.to_dict(),"graph":graph.to_dict()}

if __name__=="__main__":
    print(json.dumps(build(),indent=2,sort_keys=True))
