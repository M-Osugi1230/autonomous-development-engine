from __future__ import annotations

import unittest

from ade import (
    PilotAcceptanceCheck,
    PilotAction,
    PilotContract,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
)
from ade.pilot_preflight import (
    PilotPreflightCheck,
    PilotPreflightReport,
    PreflightCheckKind,
    PreflightCheckStatus,
    run_pilot_preflight,
)


def contract() -> PilotContract:
    return PilotContract(
        pilot_id="preflight-test",
        target=PilotTarget(
            repository="owner/repo",
            base_branch="main",
            baseline_sha="a" * 40,
        ),
        goal="Verify the production pilot before any write.",
        safety=PilotSafetyEnvelope(
            allowed_path_prefixes=("src", "tests"),
            forbidden_path_prefixes=(".github", ".autodev"),
            allowed_actions=(
                PilotAction.READ,
                PilotAction.RUN_VALIDATION,
                PilotAction.OPEN_PULL_REQUEST,
            ),
        ),
        provider_policy=PilotProviderPolicy(
            allowed_provider_ids=("jules", "github-copilot"),
            preferred_provider_ids=("jules", "github-copilot"),
        ),
        acceptance_checks=(
            PilotAcceptanceCheck(
                check_id="unit-tests",
                command="python -m unittest",
                timeout_seconds=120,
            ),
            PilotAcceptanceCheck(
                check_id="compile",
                command="python -m compileall -q src",
                timeout_seconds=120,
            ),
        ),
    )


class PilotPreflightTests(unittest.TestCase):
    def test_all_checks_pass(self) -> None:
        report = run_pilot_preflight(
            contract(),
            observed_repository="owner/repo",
            observed_base_branch="main",
            observed_baseline_sha="A" * 40,
            provider_availability=(
                ProviderAvailabilitySnapshot(
                    provider_id="jules",
                    availability=ProviderAvailability.QUOTA_PAUSED,
                    reason="quota",
                ),
                ProviderAvailabilitySnapshot(
                    provider_id="github-copilot",
                    availability=ProviderAvailability.AVAILABLE,
                ),
            ),
            acceptance_command_readiness={
                "unit-tests": True,
                "compile": True,
            },
        )
        self.assertTrue(report.passed)
        self.assertTrue(
            all(check.status is PreflightCheckStatus.PASS for check in report.checks)
        )

    def test_repository_branch_and_sha_mismatches_fail(self) -> None:
        report = run_pilot_preflight(
            contract(),
            observed_repository="other/repo",
            observed_base_branch="develop",
            observed_baseline_sha="b" * 40,
            provider_availability=(
                ProviderAvailabilitySnapshot(
                    provider_id="github-copilot",
                    availability=ProviderAvailability.AVAILABLE,
                ),
            ),
            acceptance_command_readiness={
                "unit-tests": True,
                "compile": True,
            },
        )
        self.assertFalse(report.passed)
        failed_ids = {
            check.check_id
            for check in report.checks
            if check.status is PreflightCheckStatus.FAIL
        }
        self.assertEqual(
            {"target-repository", "base-branch", "baseline-sha"},
            failed_ids,
        )

    def test_no_available_allowed_provider_fails(self) -> None:
        report = run_pilot_preflight(
            contract(),
            observed_repository="owner/repo",
            observed_base_branch="main",
            observed_baseline_sha="a" * 40,
            provider_availability=(
                ProviderAvailabilitySnapshot(
                    provider_id="jules",
                    availability=ProviderAvailability.QUOTA_PAUSED,
                    reason="quota",
                ),
                ProviderAvailabilitySnapshot(
                    provider_id="github-copilot",
                    availability=ProviderAvailability.TEMPORARILY_UNAVAILABLE,
                    reason="maintenance",
                ),
            ),
            acceptance_command_readiness={
                "unit-tests": True,
                "compile": True,
            },
        )
        self.assertFalse(report.passed)
        provider_check = next(
            check for check in report.checks
            if check.kind is PreflightCheckKind.PROVIDER_AVAILABILITY
        )
        self.assertEqual(provider_check.status, PreflightCheckStatus.FAIL)

    def test_missing_acceptance_readiness_fails_only_that_check(self) -> None:
        report = run_pilot_preflight(
            contract(),
            observed_repository="owner/repo",
            observed_base_branch="main",
            observed_baseline_sha="a" * 40,
            provider_availability=(
                ProviderAvailabilitySnapshot(
                    provider_id="jules",
                    availability=ProviderAvailability.AVAILABLE,
                ),
            ),
            acceptance_command_readiness={"unit-tests": True},
        )
        self.assertFalse(report.passed)
        failed = [
            check for check in report.checks
            if check.status is PreflightCheckStatus.FAIL
        ]
        self.assertEqual([check.check_id for check in failed], ["acceptance:compile"])

    def test_unknown_acceptance_readiness_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_pilot_preflight(
                contract(),
                observed_repository="owner/repo",
                observed_base_branch="main",
                observed_baseline_sha="a" * 40,
                provider_availability=(
                    ProviderAvailabilitySnapshot(
                        provider_id="jules",
                        availability=ProviderAvailability.AVAILABLE,
                    ),
                ),
                acceptance_command_readiness={
                    "unit-tests": True,
                    "compile": True,
                    "unknown": True,
                },
            )

    def test_report_aggregate_cannot_lie(self) -> None:
        check = PilotPreflightCheck(
            check_id="x",
            kind=PreflightCheckKind.REPOSITORY,
            status=PreflightCheckStatus.FAIL,
            message="failed",
        )
        with self.assertRaises(ValueError):
            PilotPreflightReport(
                pilot_id="test",
                passed=True,
                checks=(check,),
            )

    def test_duplicate_provider_availability_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            run_pilot_preflight(
                contract(),
                observed_repository="owner/repo",
                observed_base_branch="main",
                observed_baseline_sha="a" * 40,
                provider_availability=(
                    ProviderAvailabilitySnapshot(
                        provider_id="jules",
                        availability=ProviderAvailability.AVAILABLE,
                    ),
                    ProviderAvailabilitySnapshot(
                        provider_id="jules",
                        availability=ProviderAvailability.AVAILABLE,
                    ),
                ),
                acceptance_command_readiness={
                    "unit-tests": True,
                    "compile": True,
                },
            )


if __name__ == "__main__":
    unittest.main()
