import unittest

from ade.campaign import AutonomousCampaign, CampaignStatus
from ade.campaign_runtime import complete_campaign_task, derive_campaign_status
from ade.cycle import CycleTask
from ade.task_graph import GraphTaskStatus, TaskGraph, TaskNode


class RuntimeTests(unittest.TestCase):
    def _make_graph(self, nodes_spec):
        tasks = []
        for specification in nodes_spec:
            if len(specification) == 3:
                task_id, status, decision_id = specification
                depends_on = ()
            else:
                task_id, status, decision_id, depends_on = specification
            cycle_task = CycleTask(
                task_id=task_id,
                title=f"Task {task_id}",
                prompt=f"Prompt {task_id}",
            )
            tasks.append(
                TaskNode(
                    task=cycle_task,
                    status=status,
                    decision_id=decision_id,
                    depends_on=tuple(depends_on),
                )
            )
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

    def test_review_wait_does_not_block_independent_runnable_task(self):
        campaign = AutonomousCampaign("c1", "Goal", ("a", "b"))
        graph = self._make_graph([
            ("a", GraphTaskStatus.WAITING_REVIEW, None),
            ("b", GraphTaskStatus.PENDING, None),
        ])
        self.assertEqual(derive_campaign_status(campaign, graph), CampaignStatus.RUNNING)

    def test_review_wait_blocks_dependent_task_and_exposes_wait(self):
        campaign = AutonomousCampaign("c1", "Goal", ("a", "b"))
        graph = self._make_graph([
            ("a", GraphTaskStatus.WAITING_REVIEW, None, ()),
            ("b", GraphTaskStatus.PENDING, None, ("a",)),
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
        campaign = AutonomousCampaign(
            "c",
            "goal",
            ("a", "b"),
            CampaignStatus.RUNNING,
        )
        campaign = complete_campaign_task(campaign, "a", has_next=True)
        self.assertEqual(
            (campaign.status, campaign.progress),
            (CampaignStatus.RUNNING, (1, 2)),
        )
        campaign = complete_campaign_task(campaign, "b", has_next=False)
        self.assertEqual(campaign.status, CampaignStatus.COMPLETED)

    def test_replay_is_idempotent(self):
        campaign = AutonomousCampaign(
            "c",
            "goal",
            ("a", "b"),
            CampaignStatus.RUNNING,
            ("a",),
        )
        updated = complete_campaign_task(campaign, "a", has_next=True)
        self.assertEqual(updated.completed_task_ids, ("a",))

    def test_no_safe_next_waits(self):
        campaign = AutonomousCampaign(
            "c",
            "goal",
            ("a", "b"),
            CampaignStatus.RUNNING,
        )
        self.assertEqual(
            complete_campaign_task(campaign, "a", has_next=False).status,
            CampaignStatus.HUMAN_WAIT,
        )


if __name__ == "__main__":
    unittest.main()
