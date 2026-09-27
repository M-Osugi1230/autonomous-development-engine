import unittest
from ade.campaign import *
class CampaignTests(unittest.TestCase):
 def test_round_trip_and_progress(self):
  c=AutonomousCampaign("c1","Ship a feature",("t1","t2","t3"),CampaignStatus.RUNNING,("t1",));self.assertEqual(c.progress,(1,3));self.assertEqual(AutonomousCampaign.from_dict(c.to_dict()),c)
 def test_rejects_invalid_membership(self):
  with self.assertRaises(ValueError):AutonomousCampaign("c","g",("t1",),completed_task_ids=("other",))
 def test_rejects_duplicate_tasks(self):
  with self.assertRaises(ValueError):AutonomousCampaign("c","g",("t1","t1"))
if __name__=="__main__":unittest.main()
