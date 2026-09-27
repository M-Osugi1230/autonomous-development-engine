from __future__ import annotations

import json
import unittest

from ade.campaign import AutonomousCampaign, CampaignEvidenceSummary, CampaignStatus, summarize_campaign_evidence


class CampaignEvidenceSummaryTests(unittest.TestCase):
    def test_summarize_campaign_evidence_successful_campaign(self) -> None:
        campaign = AutonomousCampaign(
            campaign_id="cmp_12345",
            goal="Refactor authentication workflow",
            task_ids=("task-1", "task-2", "task-3"),
            status=CampaignStatus.COMPLETED,
            completed_task_ids=("task-1", "task-2", "task-3"),
        )
        summary = summarize_campaign_evidence(campaign)
        self.assertEqual(summary.campaign_id, "cmp_12345")
        self.assertEqual(summary.goal, "Refactor authentication workflow")
        self.assertEqual(summary.completed_task_count, 3)
        self.assertEqual(summary.total_task_count, 3)
        self.assertEqual(summary.terminal_status, "COMPLETED")
        self.assertEqual(summary.task_ids, ("task-1", "task-2", "task-3"))

    def test_summarize_campaign_evidence_partial_progress(self) -> None:
        campaign = AutonomousCampaign(
            campaign_id="cmp_67890",
            goal="Implement feature X",
            task_ids=("task-a", "task-b", "task-c"),
            status=CampaignStatus.RUNNING,
            completed_task_ids=("task-a",),
        )
        summary = summarize_campaign_evidence(campaign)
        self.assertEqual(summary.completed_task_count, 1)
        self.assertEqual(summary.total_task_count, 3)
        self.assertEqual(summary.terminal_status, "RUNNING")

    def test_deterministic_serialization(self) -> None:
        summary = CampaignEvidenceSummary(
            campaign_id="cmp_det_1",
            goal="Deterministic serialization check",
            completed_task_count=2,
            total_task_count=2,
            terminal_status="COMPLETED",
            task_ids=("t-1", "t-2"),
        )

        d1 = summary.to_dict()
        d2 = summary.to_dict()
        self.assertEqual(d1, d2)
        self.assertEqual(
            list(d1.keys()),
            ["schema_version", "campaign_id", "goal", "completed_task_count", "total_task_count", "terminal_status", "task_ids"],
        )

        json_str1 = summary.to_json()
        json_str2 = summary.to_json()
        self.assertEqual(json_str1, json_str2)

        expected_json = (
            '{"campaign_id":"cmp_det_1",'
            '"completed_task_count":2,'
            '"goal":"Deterministic serialization check",'
            '"schema_version":1,'
            '"task_ids":["t-1","t-2"],'
            '"terminal_status":"COMPLETED",'
            '"total_task_count":2}'
        )
        self.assertEqual(json_str1, expected_json)

        deserialized = CampaignEvidenceSummary.from_dict(d1)
        self.assertEqual(summary, deserialized)

    def test_secret_free_validation(self) -> None:
        secrets = [
            "ghp_123456789012345678901234567890123456",
            "github_pat_1234567890123456789012345678901234567890123456789012345678901234567890123456789012",
            "sk-12345678901234567890123456789012",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        ]

        for sec in secrets:
            with self.assertRaises(ValueError) as ctx:
                CampaignEvidenceSummary(
                    campaign_id=f"cmp_{sec}",
                    goal="Valid goal",
                    completed_task_count=1,
                    total_task_count=1,
                    terminal_status="COMPLETED",
                    task_ids=("task-1",),
                )
            self.assertIn("contains a forbidden secret pattern", str(ctx.exception))

            with self.assertRaises(ValueError) as ctx:
                CampaignEvidenceSummary(
                    campaign_id="cmp_safe",
                    goal=f"Goal with secret {sec}",
                    completed_task_count=1,
                    total_task_count=1,
                    terminal_status="COMPLETED",
                    task_ids=("task-1",),
                )
            self.assertIn("contains a forbidden secret pattern", str(ctx.exception))

            with self.assertRaises(ValueError) as ctx:
                CampaignEvidenceSummary(
                    campaign_id="cmp_safe",
                    goal="Valid goal",
                    completed_task_count=1,
                    total_task_count=1,
                    terminal_status="COMPLETED",
                    task_ids=(f"task-{sec}",),
                )
            self.assertIn("contains a forbidden secret pattern", str(ctx.exception))

    def test_field_validation_and_edge_cases(self) -> None:
        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="",
                goal="Goal",
                completed_task_count=0,
                total_task_count=1,
                terminal_status="COMPLETED",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="",
                completed_task_count=0,
                total_task_count=1,
                terminal_status="COMPLETED",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="Goal",
                completed_task_count=-1,
                total_task_count=1,
                terminal_status="COMPLETED",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="Goal",
                completed_task_count=2,
                total_task_count=1,
                terminal_status="COMPLETED",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="Goal",
                completed_task_count=1,
                total_task_count=1,
                terminal_status="INVALID_STATUS",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="Goal",
                completed_task_count=1,
                total_task_count=2,
                terminal_status="COMPLETED",
                task_ids=("t1",),
            )

        with self.assertRaises(ValueError):
            CampaignEvidenceSummary(
                campaign_id="cmp_1",
                goal="Goal",
                completed_task_count=2,
                total_task_count=2,
                terminal_status="COMPLETED",
                task_ids=("t1", "t1"),
            )

        with self.assertRaises(TypeError):
            summarize_campaign_evidence("not a campaign")  # type: ignore


if __name__ == "__main__":
    unittest.main()
