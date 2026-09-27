import unittest
from ade.campaign import AutonomousCampaign,CampaignStatus
from ade.campaign_runtime import complete_campaign_task
class RuntimeTests(unittest.TestCase):
 def test_progresses_and_completes(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING)
  c=complete_campaign_task(c,"a",has_next=True);self.assertEqual((c.status,c.progress),(CampaignStatus.RUNNING,(1,2)))
  c=complete_campaign_task(c,"b",has_next=False);self.assertEqual(c.status,CampaignStatus.COMPLETED)
 def test_replay_is_idempotent(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING,("a",));n=complete_campaign_task(c,"a",has_next=True);self.assertEqual(n.completed_task_ids,("a",))
 def test_no_safe_next_waits(self):
  c=AutonomousCampaign("c","goal",("a","b"),CampaignStatus.RUNNING);self.assertEqual(complete_campaign_task(c,"a",has_next=False).status,CampaignStatus.HUMAN_WAIT)
if __name__=="__main__":unittest.main()
