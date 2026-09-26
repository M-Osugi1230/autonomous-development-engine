from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "jules-cycle.yml"
TASK = ROOT / ".autodev" / "cycle-task.json"


class Phase11ProductionWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.task = json.loads(TASK.read_text(encoding="utf-8"))

    def test_production_pilot_has_a_single_push_trigger(self) -> None:
        self.assertIn('      - ".autodev/pilot/dispatch.json"', self.workflow)
        self.assertIn("    branches:\n      - main", self.workflow)
        self.assertNotIn("workflow_dispatch:", self.workflow)

    def test_normal_repository_dispatch_is_preserved(self) -> None:
        self.assertIn("repository_dispatch:", self.workflow)
        self.assertIn("      - ade_next_cycle", self.workflow)
        self.assertIn(
            "'one-minute-thought-experiments' || 'autonomous-development-engine'",
            self.workflow,
        )

    def test_existing_trusted_runner_and_secret_boundary_are_unchanged(self) -> None:
        self.assertIn("python .github/trusted/jules_cycle.py", self.workflow)
        self.assertIn("JULES_API_KEY: ${{ secrets.JULES_API_KEY }}", self.workflow)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", self.workflow)
        self.assertNotIn("curl ", self.workflow.lower())
        self.assertNotIn("wget ", self.workflow.lower())

    def test_staged_task_matches_the_frozen_pilot(self) -> None:
        self.assertEqual(
            self.task["task_id"],
            "one-minute-cli-command-guard-001",
        )
        self.assertEqual(self.task["starting_branch"], "main")
        self.assertIs(self.task["auto_create_pr"], True)
        self.assertEqual(self.task["timeout_seconds"], 1800)
        self.assertEqual(self.task["poll_interval_seconds"], 15)

    def test_staged_task_has_strict_target_scope_and_acceptance(self) -> None:
        prompt = self.task["prompt"]
        self.assertIn(
            "ONLY src/thought_pipeline/cli.py and tests/test_cli.py",
            prompt,
        )
        self.assertIn("Do not merge the pull request.", prompt)
        self.assertIn("python -m compileall -q src pipeline.py", prompt)
        self.assertIn("python pipeline.py validate", prompt)
        self.assertIn("python -m pytest -q", prompt)
        self.assertIn(
            "python pipeline.py 001 --offline --output-root /tmp/ade-pilot-output --overwrite",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
