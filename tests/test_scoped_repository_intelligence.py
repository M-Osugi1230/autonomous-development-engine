from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DIR = ROOT / ".github" / "trusted"
SRC_DIR = ROOT / "src"
for value in (str(SRC_DIR), str(TRUSTED_DIR)):
    if value not in sys.path:
        sys.path.insert(0, value)

from ade.planning_activation import PlanningGoalRequest
from github_client import GitHubClient


class FakeTreeClient(GitHubClient):
    def __init__(self) -> None:
        with patch.dict(
            os.environ,
            {"GITHUB_REPOSITORY": "owner/controller"},
            clear=False,
        ):
            super().__init__(repository="owner/target", token="test-token")

    def _request(self, method: str, path: str, payload=None):
        self.assert_request = (method, path, payload)
        return {
            "truncated": False,
            "tree": [
                {"type": "blob", "path": "operations/plan-detection/a.json"},
                {"type": "blob", "path": "operations/research-priority/current.json"},
                {"type": "blob", "path": "scripts/validate.mjs"},
                {"type": "blob", "path": "site/data/large-1.json"},
                {"type": "blob", "path": "site/data/large-2.json"},
                {"type": "tree", "path": "operations"},
            ],
        }


class ScopedRepositoryIntelligenceTests(unittest.TestCase):
    def test_planning_request_keeps_read_scope_separate_from_write_scope(self) -> None:
        request = PlanningGoalRequest.from_dict(
            {
                "schema_version": 1,
                "request_id": "scope-001",
                "campaign_id": "scope-campaign-001",
                "id_prefix": "scope001",
                "goal": "Build a bounded candidate batch.",
                "target_repository": "owner/target",
                "base_branch": "main",
                "allowed_path_prefixes": [
                    "operations/plan-detection/candidates",
                    "scripts",
                ],
                "repository_intelligence_prefixes": [
                    "operations/plan-detection",
                    "operations/research-priority",
                    "scripts",
                ],
            }
        )

        self.assertEqual(
            request.repository_intelligence_prefixes,
            (
                "operations/plan-detection",
                "operations/research-priority",
                "scripts",
            ),
        )
        self.assertEqual(
            request.planner_policy().allowed_path_prefixes,
            (
                "operations/plan-detection/candidates",
                "scripts",
            ),
        )
        self.assertEqual(
            request.to_dict()["repository_intelligence_prefixes"],
            [
                "operations/plan-detection",
                "operations/research-priority",
                "scripts",
            ],
        )

    def test_tree_budget_counts_only_selected_read_scope(self) -> None:
        client = FakeTreeClient()
        paths = client.list_tree_paths(
            "owner/target",
            tree_sha="a" * 40,
            max_entries=3,
            include_prefixes=(
                "operations/plan-detection",
                "operations/research-priority",
                "scripts",
            ),
        )
        self.assertEqual(
            paths,
            [
                "operations/plan-detection/a.json",
                "operations/research-priority/current.json",
                "scripts/validate.mjs",
            ],
        )

    def test_tree_scope_does_not_expand_mutation_authority(self) -> None:
        request = PlanningGoalRequest(
            request_id="scope-002",
            campaign_id="scope-campaign-002",
            id_prefix="scope002",
            goal="Read broadly enough to plan, write narrowly.",
            target_repository="owner/target",
            base_branch="main",
            allowed_path_prefixes=("scripts",),
            repository_intelligence_prefixes=(
                "operations/research-priority",
                "scripts",
            ),
        )
        self.assertEqual(
            request.planner_policy().allowed_path_prefixes,
            ("scripts",),
        )


if __name__ == "__main__":
    unittest.main()
