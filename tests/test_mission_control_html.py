from __future__ import annotations

import unittest

from ade import (
    MissionCheckpointSummary,
    MissionControlSnapshot,
    MissionDecisionSummary,
    MissionTelemetrySummary,
    render_mission_control,
)


def make_snapshot(
    *,
    project_id: str = "ade-test",
    warnings: tuple[str, ...] = ("telemetry metrics lag project iteration",),
    decisions: tuple[MissionDecisionSummary, ...] | None = None,
) -> MissionControlSnapshot:
    if decisions is None:
        decisions = (
            MissionDecisionSummary(
                decision_id="decision-1",
                question="Approve the irreversible migration?",
                options=("approve", "reject"),
                priority="P0",
                blocking_task_id="task-5",
            ),
        )
    return MissionControlSnapshot(
        project_id=project_id,
        project_status="RUNNING",
        iteration=5,
        current_task_id="task-5",
        state_updated_at="2026-09-26T01:00:00+00:00",
        phase="phase8-mission-control",
        milestone="html-renderer",
        completed_tasks=4,
        failed_tasks=1,
        queue_depth=2,
        queue_exhausted=False,
        failure_ledger_count=1,
        checkpoint=MissionCheckpointSummary(
            task_id="task-5",
            state="RUNNING",
            attempt=1,
            replan_count=0,
            failure_kind=None,
            resume_after=None,
            provider_session_present=True,
        ),
        open_decisions=decisions,
        telemetry=MissionTelemetrySummary(
            cycles_started=2,
            cycles_completed=1,
            repair_attempts=1,
            human_interrupts=1,
            quota_pauses=1,
        ),
        warnings=warnings,
    )


class MissionControlHtmlTests(unittest.TestCase):
    def test_renderer_shows_representative_snapshot(self) -> None:
        html = render_mission_control(make_snapshot())

        self.assertIn("<!doctype html>", html)
        self.assertIn("Mission Control", html)
        self.assertIn("ade-test", html)
        self.assertIn("phase8-mission-control", html)
        self.assertIn("html-renderer", html)
        self.assertIn("task-5", html)
        self.assertIn("Approve the irreversible migration?", html)
        self.assertIn("decision-1", html)
        self.assertIn("telemetry metrics lag project iteration", html)
        self.assertIn("Provider session", html)
        self.assertIn(">present<", html)

    def test_all_dynamic_values_are_escaped(self) -> None:
        malicious = MissionDecisionSummary(
            decision_id='decision-<x>',
            question='<img src=x onerror="boom"> & choose?',
            options=("<approve>", '"reject"'),
            priority="P0",
            blocking_task_id="<task>",
        )
        html = render_mission_control(
            make_snapshot(
                project_id='<script>alert("x")</script>',
                warnings=('<b>warning</b> & "quoted"',),
                decisions=(malicious,),
            )
        )

        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertNotIn('<img src=x onerror="boom">', html)
        self.assertNotIn("<b>warning</b>", html)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=&quot;boom&quot;&gt; &amp; choose?", html)
        self.assertIn("&lt;b&gt;warning&lt;/b&gt; &amp; &quot;quoted&quot;", html)

    def test_document_has_no_javascript_or_external_resources(self) -> None:
        html = render_mission_control(make_snapshot())
        lowered = html.lower()

        self.assertNotIn("<script", lowered)
        self.assertNotIn("javascript:", lowered)
        self.assertNotIn("http://", lowered)
        self.assertNotIn("https://", lowered)
        self.assertNotIn("<link", lowered)
        self.assertNotIn("@import", lowered)
        self.assertNotIn(" src=", lowered)

    def test_empty_decisions_and_warnings_render_clear_messages(self) -> None:
        html = render_mission_control(
            make_snapshot(
                warnings=(),
                decisions=(),
            )
        )

        self.assertIn("No open human decisions.", html)
        self.assertIn("No warnings.", html)

    def test_missing_checkpoint_renders_empty_state(self) -> None:
        snapshot = make_snapshot()
        without_checkpoint = MissionControlSnapshot(
            project_id=snapshot.project_id,
            project_status=snapshot.project_status,
            iteration=snapshot.iteration,
            current_task_id=snapshot.current_task_id,
            state_updated_at=snapshot.state_updated_at,
            phase=snapshot.phase,
            milestone=snapshot.milestone,
            completed_tasks=snapshot.completed_tasks,
            failed_tasks=snapshot.failed_tasks,
            queue_depth=snapshot.queue_depth,
            queue_exhausted=snapshot.queue_exhausted,
            failure_ledger_count=snapshot.failure_ledger_count,
            checkpoint=None,
            open_decisions=snapshot.open_decisions,
            telemetry=snapshot.telemetry,
            warnings=snapshot.warnings,
        )

        html = render_mission_control(without_checkpoint)
        self.assertIn("No checkpoint is present.", html)

    def test_renderer_rejects_non_snapshot_input(self) -> None:
        with self.assertRaises(ValueError):
            render_mission_control({"project_id": "bad"})  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
