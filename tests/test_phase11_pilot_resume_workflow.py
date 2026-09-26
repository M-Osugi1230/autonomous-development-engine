from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "ade-resume.yml"
)


class Phase11PilotResumeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_resume_is_temporarily_routed_to_frozen_pilot_target(self) -> None:
        self.assertIn(
            "ADE_GITHUB_REPO: one-minute-thought-experiments",
            self.text,
        )
        self.assertNotIn(
            "ADE_GITHUB_REPO: autonomous-development-engine",
            self.text,
        )

    def test_resume_runs_just_after_the_quota_release_window(self) -> None:
        self.assertIn('cron: "47 * * * *"', self.text)

    def test_existing_trusted_resume_boundary_is_preserved(self) -> None:
        self.assertIn("python .github/trusted/jules_resume.py", self.text)
        self.assertIn("JULES_API_KEY: ${{ secrets.JULES_API_KEY }}", self.text)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.text)
        self.assertIn("contents: write", self.text)
        self.assertNotIn("curl ", self.text.lower())
        self.assertNotIn("wget ", self.text.lower())


if __name__ == "__main__":
    unittest.main()
