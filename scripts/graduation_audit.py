from __future__ import annotations
import json
from pathlib import Path

REQUIRED_PROOFS=(
 "Execution lease duplicate-dispatch proof",
 "Production fault-injection proof",
 "Long-running campaign restart proof",
 "Mission Control observability proof",
 "Autonomous recovery fault proof",
 "Multi-provider routing proof",
 "Checkpoint restart proof",
 "Human decision boundary proof",
)

def audit(root:Path)->dict[str,object]:
    ci=(root/".github/workflows/ci.yml").read_text()
    missing=[name for name in REQUIRED_PROOFS if name not in ci]
    p15=json.loads((root/".autodev/campaign-evidence/phase15-recovery-campaign-001.json").read_text())
    p16=json.loads((root/".autodev/campaign-evidence/phase16-goal-campaign-001.json").read_text())
    checks={
      "required_proofs_declared":not missing,
      "real_recovery_green":p15.get("terminal_outcome")=="RECOVERED_TO_GREEN_AND_MERGED",
      "goal_campaign_completed":p16.get("terminal_status")=="COMPLETED",
      "goal_campaign_multi_task":len(p16.get("tasks",[]))>=2,
      "no_manual_between_goal_tasks":p16.get("manual_dispatch_between_tasks") is False,
    }
    return {"schema_version":1,"checks":checks,"missing_proofs":missing,"ready_for_final_campaign":all(checks.values())}

if __name__=="__main__":
    result=audit(Path("."))
    print(json.dumps(result,indent=2,sort_keys=True))
    if not result["ready_for_final_campaign"]: raise SystemExit(1)
