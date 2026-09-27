import unittest
from ade.campaign import AutonomousCampaign, CampaignStatus
from ade.campaign_runtime import complete_campaign_task, derive_campaign_status
from ade.cycle import CycleTask
from ade.task_graph import GraphTaskStatus, TaskGraph, TaskNode

class RuntimeTests(unittest.TestCase):
 def _make_graph(self, nodes_spec):
  tasks = []
  for task_id, status, decision_id in nodes_spec:
   cycle_task = CycleTask(task_id=task_id, title=f"Task {task_id}", prompt=f"Prompt {task_id}")
   tasks.append(TaskNode(task=cycle_task, status=status, decision_id=decision_id))
  return TaskGraph(tasks=tuple(tasks))

 def test_derive_campaign_status_partial_progress(self):
  campaign = AutonomousCampaign("c1", "Goal", ("t1", "t2"))
  graph = self._make_graph([
   ("t1", GraphTaskStatus.COMPLETED, None),
   ("t2", GraphTaskStatus.PENDING, None),
  ])
  self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.RUNNING)

 def test_derive_campaign_status_complete(self):
  campaign = AutonomousCampaign("c1", "Goal", ("t1", "t2"))
  graph = self._make_graph([
   ("t1", GraphTaskStatus.COMPLETED, None),
   ("t2", GraphTaskStatus.COMPLETED, None),
  ])
  self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.COMPLETED)

 def test_derive_campaign_status_human_wait(self):
  campaign = AutonomousCampaign("c1", "Goal", ("t1", "t2"))
  graph = self._make_graph([
   ("t1", GraphTaskStatus.COMPLETED, None),
   ("t2", GraphTaskStatus.HUMAN_WAIT, "dec-1"),
  ])
  self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.HUMAN_WAIT)

 def test_derive_campaign_status_failed(self):
  campaign = AutonomousCampaign("c1", "Goal", ("t1", "t2"))
  graph = self._make_graph([
   ("t1", GraphTaskStatus.COMPLETED, None),
   ("t2", GraphTaskStatus.FAILED, None),
  ])
  self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.FAILED)

 def test_derive_campaign_status_unrelated_graph_tasks(self):
  campaign = AutonomousCampaign("c1", "Goal", ("t1", "t2"))
  graph = self._make_graph([
   ("t1", GraphTaskStatus.COMPLETED, None),
   ("t2", GraphTaskStatus.COMPLETED, None),
   ("unrelated_failed", GraphTaskStatus.FAILED, None),
   ("unrelated_wait", GraphTaskStatus.HUMAN_WAIT, "dec-unrelated"),
  ])
  self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.COMPLETED)
 def test_progresses_and_completes(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING)
  c=complete_campaign_task(c,"a",has_next=True);self.assertEqual((c.status,c.progress),(CampaignStatus.RUNNING,(1,2)))
  c=complete_campaign_task(c,"b",has_next=False);self.assertEqual(c.status,CampaignStatus.COMPLETED)
 def test_replay_is_idempotent(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING,("a",));n=complete_campaign_task(c,"a",has_next=True);self.assertEqual(n.completed_task_ids,("a",))
 def test_no_safe_next_waits(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING);self.assertEqual(complete_campaign_task(c,"a",has_next=False).status,CampaignStatus.HUMAN_WAIT)
if __name__=="__main__":unittest.main()
