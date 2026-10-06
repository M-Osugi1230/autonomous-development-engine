from __future__ import annotations

import unittest

from ade.control_center import (
    ControlCenterPortfolioSnapshot,
    ControlCenterProjectSummary,
)
from ade.control_center_html import render_control_center


class ControlCenterHtmlTests(unittest.TestCase):
    def project(
        self,
        project_id: str,
        *,
        lifecycle: str = "RUNNING",
        human_action_required: bool = False,
    ) -> ControlCenterProjectSummary:
        return ControlCenterProjectSummary(
            project_id=project_id,
            lifecycle_status=lifecycle,
            project_status="RUNNING",
            current_task_id="task-1",
            state_updated_at="2026-10-06T08:00:00+00:00",
            completed_tasks=2,
            total_tasks=4,
            progress_percent=50,
            queue_depth=2,
            failed_tasks=0,
            open_decision_count=1 if human_action_required else 0,
            warning_count=0,
            human_action_required=human_action_required,
            next_required_human_action=(
                "Review trusted decision" if human_action_required else None
            ),
            next_system_action="continue trusted execution",
            resume_after=None,
            phase="v0.2",
            milestone="portfolio",
        )

    def test_renderer_shows_multiple_projects_and_attention(self) -> None:
        snapshot = ControlCenterPortfolioSnapshot(
            projects=(
                self.project("j-quants"),
                self.project(
                    "jichi",
                    lifecycle="HUMAN_WAIT",
                    human_action_required=True,
                ),
                self.project("chu-kei", lifecycle="RECOVERING"),
            )
        )

        html = render_control_center(snapshot)

        self.assertIn("ADE Control Center", html)
        self.assertIn("j-quants", html)
        self.assertIn("jichi", html)
        self.assertIn("chu-kei", html)
        self.assertIn("Human action required", html)
        self.assertIn("No human action", html)
        self.assertIn("RECOVERING", html)
        self.assertIn("50%", html)

    def test_renderer_escapes_dynamic_values(self) -> None:
        snapshot = ControlCenterPortfolioSnapshot(
            projects=(self.project('<img src=x onerror="bad">'),)
        )
        html = render_control_center(snapshot)

        self.assertNotIn('<img src=x onerror="bad">', html)
        self.assertIn("&lt;img src=x onerror=&quot;bad&quot;&gt;", html)

    def test_renderer_has_no_javascript_or_external_resources(self) -> None:
        html = render_control_center(
            ControlCenterPortfolioSnapshot(projects=(self.project("j-quants"),))
        )
        lowered = html.lower()

        self.assertNotIn("<script", lowered)
        self.assertNotIn("javascript:", lowered)
        self.assertNotIn("<link", lowered)
        self.assertNotIn(" src=", lowered)
        self.assertNotIn("@import", lowered)

    def test_empty_portfolio_renders_clear_state(self) -> None:
        html = render_control_center(ControlCenterPortfolioSnapshot(projects=()))
        self.assertIn("No ADE-managed projects are available.", html)
        self.assertIn(">0<", html)

    def test_renderer_rejects_wrong_input(self) -> None:
        with self.assertRaises(ValueError):
            render_control_center(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
