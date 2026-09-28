from __future__ import annotations
import json
import re
from pathlib import Path

REQUIRED_PROOFS=(
 "Execution lease duplicate-dispatch proof","Production fault-injection proof",
 "Long-running campaign restart proof","Mission Control observability proof",
 "Autonomous recovery fault proof","Multi-provider routing proof",
 "Checkpoint restart proof","Human decision boundary proof",
)

_SHA40=re.compile(r"^[0-9a-f]{40}$")

def _graduation_task_evidence(task:object)->bool:
    if not isinstance(task,dict): return False
    return (
      isinstance(task.get("task_id"),str) and bool(task["task_id"].strip())
      and type(task.get("pull_request")) is int and task["pull_request"]>0
      and type(task.get("ci_run")) is int and task["ci_run"]>0
      and isinstance(task.get("merge_commit"),str)
      and _SHA40.fullmatch(task["merge_commit"]) is not None
    )

def audit(root:Path)->dict[str,object]:
    ci=(root/".github/workflows/ci.yml").read_text()
    missing=[name for name in REQUIRED_PROOFS if name not in ci]
    p15=json.loads((root/".autodev/campaign-evidence/phase15-recovery-campaign-001.json").read_text())
    p16=json.loads((root/".autodev/campaign-evidence/phase16-goal-campaign-001.json").read_text())
    p17=json.loads((root/".autodev/campaign-evidence/phase17-production-graduation-001.json").read_text())
    graduation_tasks=p17.get("tasks",[])
    checks={
      "required_proofs_declared":not missing,
      "real_recovery_green":p15.get("terminal_outcome")=="RECOVERED_TO_GREEN_AND_MERGED",
      "goal_campaign_completed":p16.get("terminal_status")=="COMPLETED",
      "goal_campaign_multi_task":len(p16.get("tasks",[]))>=2,
      "graduation_campaign_id":p17.get("campaign_id")=="phase17-production-graduation-001",
      "graduation_campaign_completed":p17.get("terminal_status")=="COMPLETED",
      "graduation_three_tasks":isinstance(graduation_tasks,list) and len(graduation_tasks)>=3,
      "graduation_task_evidence_complete":isinstance(graduation_tasks,list) and all(_graduation_task_evidence(task) for task in graduation_tasks),
      "graduation_no_failed_tasks":p17.get("failed_tasks")==0,
      "graduation_no_manual_between_tasks":p17.get("manual_dispatch_between_tasks") is False,
    }
    return {"schema_version":1,"checks":checks,"missing_proofs":missing,"production_graduated":all(checks.values())}

if __name__=="__main__":
    result=audit(Path("."))
    print(json.dumps(result,indent=2,sort_keys=True))
    if not result["production_graduated"]: raise SystemExit(1)
