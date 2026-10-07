from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import completion_planner_cycle as completion_planner
from ade.planner_path_grounding import plan_high_level_goal_with_path_grounding


# The completion controller deliberately imports the normal planner module and
# delegates into its main() function. Replace only the planner-call boundary so
# all existing activation, evidence, quota, and human-safety behavior remains
# unchanged while ADE-derived native-plan paths are grounded against the trusted
# repository snapshot.
completion_planner.planner_cycle.plan_high_level_goal = (
    plan_high_level_goal_with_path_grounding
)


if __name__ == "__main__":
    raise SystemExit(completion_planner.main())
