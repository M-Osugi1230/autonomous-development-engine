from __future__ import annotations

import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "mission-control.yml"
)


class MissionControlWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.text.lower()

    def test_workflow_is_read_only(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("contents: write", self.lowered)
        self.assertNotIn("write-all", self.lowered)
        self.assertNotIn("pull-requests: write", self.lowered)
        self.assertNotIn("actions: write", self.lowered)

    def test_workflow_receives_no_secrets_or_privileged_tokens(self) -> None:
        self.assertNotIn("JULES_API_KEY", self.text)
        self.assertNotIn("GITHUB_TOKEN", self.text)
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("github.token", self.lowered)

    def test_workflow_does_not_deploy_or_request_pages_permissions(self) -> None:
        self.assertNotIn("deploy-pages", self.lowered)
        self.assertNotIn("pages: write", self.lowered)
        self.assertNotIn("id-token: write", self.lowered)
        self.assertNotIn("github-pages", self.lowered)

    def test_workflow_builds_with_public_cli_and_uploads_artifact(self) -> None:
        self.assertIn("python scripts/build_mission_control.py", self.text)
        self.assertIn("actions/upload-artifact@v4", self.text)
        self.assertIn("path: dist/mission-control", self.text)
        self.assertIn("name: ade-mission-control", self.text)

    def test_workflow_has_no_external_deployment_commands(self) -> None:
        for forbidden in (
            "curl ",
            "wget ",
            "scp ",
            "rsync ",
            "firebase ",
            "vercel ",
            "netlify ",
        ):
            self.assertNotIn(forbidden, self.lowered)


if __name__ == "__main__":
    unittest.main()
