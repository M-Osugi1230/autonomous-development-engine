from __future__ import annotations

import unittest

from ade.pr_gate import evaluate_jules_pull_request


def jules_pr(*, branch: str = "feat/demo", body: str | None = None):
    return {
        "state": "open",
        "draft": False,
        "body": body
        or (
            "Implemented requested change.\n\n"
            "---\n*PR created automatically by Jules for task "
            "[123](https://jules.google.com/task/123)*"
        ),
        "head": {
            "ref": branch,
            "sha": "abc123",
            "repo": {"full_name": "owner/repo"},
        },
    }


class GatePolicyTests(unittest.TestCase):
    def test_allows_scoped_jules_change(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(),
            files=[
                {"filename": "src/ade/example.py"},
                {"filename": "tests/test_example.py"},
            ],
        )
        self.assertTrue(decision.allowed)

    def test_allows_non_feat_jules_branch_when_provenance_is_valid(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(branch="add-decision-model-2493404388033472197"),
            files=[{"filename": "src/ade/decisions.py"}],
        )
        self.assertTrue(decision.allowed)

    def test_rejects_workflow_change(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(),
            files=[{"filename": ".github/workflows/ci.yml"}],
        )
        self.assertFalse(decision.allowed)
        self.assertIn("forbidden path", decision.reason)

    def test_rejects_autodev_state_change(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(),
            files=[{"filename": ".autodev/state.json"}],
        )
        self.assertFalse(decision.allowed)

    def test_rejects_non_jules_provenance(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(body="ordinary pull request"),
            files=[{"filename": "src/ade/example.py"}],
        )
        self.assertFalse(decision.allowed)
        self.assertIn("provenance", decision.reason)

    def test_rejects_marker_without_jules_task_url(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(
                body="PR created automatically by Jules for task but no valid task URL"
            ),
            files=[{"filename": "src/ade/example.py"}],
        )
        self.assertFalse(decision.allowed)

    def test_rejects_fork(self):
        pr = jules_pr()
        pr["head"]["repo"]["full_name"] = "other/repo"
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=pr,
            files=[{"filename": "src/ade/example.py"}],
        )
        self.assertFalse(decision.allowed)

    def test_rejects_default_branch_as_head(self):
        decision = evaluate_jules_pull_request(
            repository="owner/repo",
            pull_request=jules_pr(branch="main"),
            files=[{"filename": "src/ade/example.py"}],
        )
        self.assertFalse(decision.allowed)


if __name__ == "__main__":
    unittest.main()
