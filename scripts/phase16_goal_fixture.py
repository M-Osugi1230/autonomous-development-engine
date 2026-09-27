from ade.goal_planner import GoalWorkItem, plan_goal
from ade.accepted_plan import AcceptedPlan
from ade.plan_compiler import compile_plan
import json
items=(
 GoalWorkItem("Implement text normalization utility","Add a pure normalize_text helper that trims surrounding whitespace and collapses internal whitespace.",("src/ade/text_normalization.py",),("normalize_text is pure and deterministic","empty or whitespace-only input returns an empty string")),
 GoalWorkItem("Prove text normalization behavior","Add focused stdlib unit tests for normalize_text covering normal, repeated whitespace, newline, and empty inputs.",("tests/test_text_normalization.py",),("focused tests cover the required normalization cases","full repository tests remain green"),(1,)),
)
plan=plan_goal("Add a small reusable text normalization utility and prove it with focused tests.",items,id_prefix="phase16-goal")
accepted=AcceptedPlan.accept(plan)
campaign,graph=compile_plan(plan,campaign_id="phase16-goal-campaign-001")
print(json.dumps({"accepted":accepted.to_dict(),"campaign":campaign.to_dict(),"graph":graph.to_dict()},indent=2,sort_keys=True))
