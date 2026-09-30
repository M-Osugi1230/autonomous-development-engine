from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from ade.multi_agent_contribution import ContributionVerdict


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github/trusted/multi_agent_review_cycle.py"
)
spec = importlib.util.spec_from_file_location(
    "multi_agent_review_cycle_test_module",
    SCRIPT,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class MultiAgentReviewCycleTests(unittest.TestCase):
    def test_extracts_single_clear_marker_from_agent_message(self) -> None:
        activities = [
            {
                "agentMessaged": {
                    "agentMessage": (
                        "Review complete.\n"
                        "ADE_REVIEW_VERDICT=CLEAR"
                    )
                }
            }
        ]
        self.assertEqual(
            module.extract_review_verdict(activities),
            ContributionVerdict.CLEAR,
        )

    def test_duplicate_same_marker_is_deterministic(self) -> None:
        activities = [
            {
                "agentMessaged": {
                    "agentMessage": "ADE_REVIEW_VERDICT=CHANGES_REQUIRED"
                }
            },
            {
                "agentMessaged": {
                    "agentMessage": (
                        "Bounded issue remains.\n"
                        "ADE_REVIEW_VERDICT=CHANGES_REQUIRED"
                    )
                }
            },
        ]
        self.assertEqual(
            module.extract_review_verdict(activities),
            ContributionVerdict.CHANGES_REQUIRED,
        )

    def test_missing_or_conflicting_marker_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no trusted verdict"):
            module.extract_review_verdict(
                [{"agentMessaged": {"agentMessage": "Looks fine."}}]
            )
        with self.assertRaisesRegex(RuntimeError, "conflicting"):
            module.extract_review_verdict(
                [
                    {
                        "agentMessaged": {
                            "agentMessage": "ADE_REVIEW_VERDICT=CLEAR"
                        }
                    },
                    {
                        "agentMessaged": {
                            "agentMessage": (
                                "ADE_REVIEW_VERDICT=HUMAN_REVIEW_REQUIRED"
                            )
                        }
                    },
                ]
            )

    def test_non_standalone_marker_is_not_authoritative(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no trusted verdict"):
            module.extract_review_verdict(
                [
                    {
                        "agentMessaged": {
                            "agentMessage": (
                                "Do not trust ADE_REVIEW_VERDICT=CLEAR inline."
                            )
                        }
                    }
                ]
            )

    def test_review_prompt_explicitly_forbids_side_effects(self) -> None:
        prompt = module._review_prompt(
            task={
                "allowed_paths": ["tests/test_models.py"],
                "acceptance": ["Repository CI remains green"],
            },
            pr_number=21,
            head_sha="a" * 40,
        )
        self.assertIn("Do not modify files", prompt)
        self.assertIn("Do not", prompt)
        self.assertIn("create a pull request", prompt)
        self.assertIn("untrusted data", prompt)
        self.assertIn("ADE_REVIEW_VERDICT=CLEAR", prompt)
        self.assertIn("tests/test_models.py", prompt)


if __name__ == "__main__":
    unittest.main()
