from __future__ import annotations
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
from ade.campaign import AutonomousCampaign,CampaignStatus
from ade.campaign_runtime import complete_campaign_task
from ade.cycle import CycleTask
from ade.task_graph import TaskGraph,TaskNode,GraphTaskStatus
from ade.task_graph_transition import transition_task\nfrom ade.task_scheduler import next_runnable_task

def task(i): return CycleTask(task_id=f"t{i}",title=f"T{i}",prompt=f"Do {i}",starting_branch="main")
def main():
 nodes=[] 
 for i in range(1,7): nodes.append(TaskNode(task(i),depends_on=(() if i==1 else (f"t{i-1}",)),status=(GraphTaskStatus.RUNNING if i==1 else GraphTaskStatus.PENDING)))
 graph=TaskGraph(tuple(nodes)); campaign=AutonomousCampaign("campaign-1","Complete six safe slices",tuple(f"t{i}" for i in range(1,7)),CampaignStatus.RUNNING)
 sequence=[]
 for i in range(1,4):
  graph=transition_task(graph,task_id=f"t{i}",target_status=GraphTaskStatus.COMPLETED);nxt=next_runnable_task(graph);\n  if nxt is not None: graph=transition_task(graph,task_id=nxt.task_id,target_status=GraphTaskStatus.RUNNING)\n  campaign=complete_campaign_task(campaign,f"t{i}",has_next=nxt is not None);sequence.append(f"t{i}")
 # simulated process restart: serialize all durable state, then reload it
 graph=TaskGraph.from_dict(graph.to_dict());campaign=AutonomousCampaign.from_dict(campaign.to_dict())
 assert campaign.completed_task_ids==("t1","t2","t3")
 for i in range(4,7):
  graph,nxt=complete_and_schedule_next(graph,completed_task_id=f"t{i}");campaign=complete_campaign_task(campaign,f"t{i}",has_next=nxt is not None);sequence.append(f"t{i}")
 assert campaign.status==CampaignStatus.COMPLETED and campaign.progress==(6,6)
 assert sequence==["t1","t2","t3","t4","t5","t6"]
 print(json.dumps({"ok":True,"transitions":6,"restart_after":"t3","replayed_completed_tasks":False,"terminal_status":campaign.status.value},sort_keys=True,separators=(",",":")))
 return 0
if __name__=="__main__":raise SystemExit(main())
