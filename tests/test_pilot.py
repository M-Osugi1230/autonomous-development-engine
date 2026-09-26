from __future__ import annotations

import unittest

from ade.pilot import (
    PilotAcceptanceCheck,
    PilotAction,
    PilotContract,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
)


class PilotContractTests(unittest.TestCase):
    def build_contract(self) -> PilotContract:
        return PilotContract(
            pilot_id="pilot-001",
            target=PilotTarget(
                repository="owner/repo",
                base_branch="main",
                baseline_sha="a" * 40,
            ),
            goal="Ship one bounded, reviewable change.",
            safety=PilotSafetyEnvelope(
                allowed_path_prefixes=("src", "tests"),
                forbidden_path_prefixes=(".github/workflows", ".autodev"),
                allowed_actions=(
                    PilotAction.READ,
                    PilotAction.CREATE_BRANCH,
                    PilotAction.MODIFY_FILES,
                    PilotAction.RUN_VALIDATION,
                    PilotAction.OPEN_PULL_REQUEST,
                    PilotAction.COMMENT,
                ),
                max_tasks=3,
                max_consecutive_failures=2,
                require_human_activation=True,
            ),
            provider_policy=PilotProviderPolicy(
                allowed_provider_ids=("jules", "github-copilot"),
                preferred_provider_ids=("jules", "github-copilot"),
                allow_fallback_before_session=True,
                sticky_after_session=True,
            ),
            acceptance_checks=(
                PilotAcceptanceCheck(
                    check_id="unit-tests",
                    command="PYTHONPATH=src python -m unittest discover -s tests -v",
                    timeout_seconds=900,
                ),
            ),
        )

    def test_round_trip_serialization_is_deterministic(self) -> None:
        contract = self.build_contract()
        payload = contract.to_dict()
        restored = PilotContract.from_dict(payload)
        self.assertEqual(restored, contract)
        self.assertEqual(restored.to_dict(), payload)

    def test_target_requires_repository_branch_and_baseline_sha(self) -> None:
        with self.assertRaises(ValueError):
            PilotTarget(repository="owner-only", base_branch="main", baseline_sha="a" * 40)
        with self.assertRaises(ValueError):
            PilotTarget(repository="owner/repo", base_branch="", baseline_sha="a" * 40)
        with self.assertRaises(ValueError):
            PilotTarget(repository="owner/repo", base_branch="main", baseline_sha="xyz")

    def test_path_forbidden_prefix_overrides_allowlist(self) -> None:
        safety = self.build_contract().safety
        self.assertTrue(safety.path_allowed("src/ade/pilot.py"))
        self.assertTrue(safety.path_allowed("tests/test_pilot.py"))
        self.assertFalse(safety.path_allowed(".github/workflows/ci.yml"))
        self.assertFalse(safety.path_allowed("README.md"))

    def test_unsafe_paths_are_rejected(self) -> None:
        safety = self.build_contract().safety
        for value in ("/etc/passwd", "../secret", "./src/file.py"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    safety.path_allowed(value)

        with self.assertRaises(ValueError):
            PilotSafetyEnvelope(
                allowed_path_prefixes=("../src",),
                forbidden_path_prefixes=(".github",),
                allowed_actions=(
                    PilotAction.READ,
                    PilotAction.RUN_VALIDATION,
                    PilotAction.OPEN_PULL_REQUEST,
                ),
            )

    def test_required_safe_actions_cannot_be_omitted(self) -> None:
        with self.assertRaises(ValueError):
            PilotSafetyEnvelope(
                allowed_path_prefixes=("src",),
                forbidden_path_prefixes=(".github",),
                allowed_actions=(PilotAction.READ,),
            )

    def test_merge_is_not_an_available_pilot_action(self) -> None:
        with self.assertRaises(ValueError):
            PilotAction("MERGE")

    def test_provider_policy_requires_sticky_resume(self) -> None:
        with self.assertRaises(ValueError):
            PilotProviderPolicy(
                allowed_provider_ids=("jules", "github-copilot"),
                preferred_provider_ids=("jules",),
                sticky_after_session=False,
            )

    def test_preferred_provider_must_be_allowed(self) -> None:
        with self.assertRaises(ValueError):
            PilotProviderPolicy(
                allowed_provider_ids=("jules",),
                preferred_provider_ids=("github-copilot",),
            )

    def test_acceptance_checks_require_unique_ids(self) -> None:
        base = self.build_contract()
        duplicate = PilotAcceptanceCheck(
            check_id="unit-tests",
            command="python -m unittest",
        )
        with self.assertRaises(ValueError):
            PilotContract(
                pilot_id=base.pilot_id,
                target=base.target,
                goal=base.goal,
                safety=base.safety,
                provider_policy=base.provider_policy,
                acceptance_checks=(base.acceptance_checks[0], duplicate),
            )

    def test_contract_rejects_unsupported_schema(self) -> None:
        base = self.build_contract()
        payload = base.to_dict()
        payload["schema_version"] = 2
        with self.assertRaises(ValueError):
            PilotContract.from_dict(payload)

    def test_limits_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            PilotSafetyEnvelope(
                allowed_path_prefixes=("src",),
                forbidden_path_prefixes=(".github",),
                allowed_actions=(
                    PilotAction.READ,
                    PilotAction.RUN_VALIDATION,
                    PilotAction.OPEN_PULL_REQUEST,
                ),
                max_tasks=0,
            )
        with self.assertRaises(ValueError):
            PilotSafetyEnvelope(
                allowed_path_prefixes=("src",),
                forbidden_path_prefixes=(".github",),
                allowed_actions=(
                    PilotAction.READ,
                    PilotAction.RUN_VALIDATION,
                    PilotAction.OPEN_PULL_REQUEST,
                ),
                max_consecutive_failures=6,
            )


if __name__ == "__main__":
    unittest.main()
