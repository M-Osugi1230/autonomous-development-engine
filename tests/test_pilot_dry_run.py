from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ade import (
    DryRunCheckStatus,
    PilotAcceptanceCheck,
    PilotAction,
    PilotContract,
    PilotDryRunOperation,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
    ProviderAvailability,
    ProviderAvailabilitySnapshot,
    build_pilot_activation,
    run_pilot_dry_run,
    run_pilot_preflight,
)


def contract() -> PilotContract:
    return PilotContract(
        pilot_id="dry-run-pilot",
        target=PilotTarget(
            repository="owner/production-repo",
            base_branch="main",
            baseline_sha="a" * 40,
        ),
        goal="Apply one bounded production change.",
        safety=PilotSafetyEnvelope(
            allowed_path_prefixes=("src", "tests"),
            forbidden_path_prefixes=(".github", ".autodev", "src/secrets"),
            allowed_actions=(
                PilotAction.READ,
                PilotAction.CREATE_BRANCH,
                PilotAction.MODIFY_FILES,
                PilotAction.RUN_VALIDATION,
                PilotAction.OPEN_PULL_REQUEST,
            ),
            require_human_activation=True,
        ),
        provider_policy=PilotProviderPolicy(
            allowed_provider_ids=("jules", "github-copilot"),
            preferred_provider_ids=("jules",),
        ),
        acceptance_checks=(
            PilotAcceptanceCheck(
                check_id="unit-tests",
                command="python -m unittest",
                timeout_seconds=120,
            ),
        ),
    )


def passing_preflight(current: PilotContract):
    return run_pilot_preflight(
        current,
        observed_repository=current.target.repository,
        observed_base_branch=current.target.base_branch,
        observed_baseline_sha=current.target.baseline_sha,
        provider_availability=(
            ProviderAvailabilitySnapshot(
                provider_id="jules",
                availability=ProviderAvailability.AVAILABLE,
            ),
        ),
        acceptance_command_readiness={"unit-tests": True},
    )


class PilotDryRunTests(unittest.TestCase):
    def test_allowed_plan_passes_and_produces_deterministic_evidence(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        report = run_pilot_dry_run(
            current,
            preflight=passing_preflight(current),
            activation=activation,
            operations=(
                PilotDryRunOperation(
                    operation_id="read-source",
                    action=PilotAction.READ,
                    path="src/app.py",
                ),
                PilotDryRunOperation(
                    operation_id="create-branch",
                    action=PilotAction.CREATE_BRANCH,
                ),
                PilotDryRunOperation(
                    operation_id="modify-source",
                    action=PilotAction.MODIFY_FILES,
                    path="src/app.py",
                ),
                PilotDryRunOperation(
                    operation_id="validate",
                    action=PilotAction.RUN_VALIDATION,
                ),
                PilotDryRunOperation(
                    operation_id="open-pr",
                    action=PilotAction.OPEN_PULL_REQUEST,
                ),
            ),
        )

        self.assertTrue(report.passed)
        self.assertTrue(report.preflight_passed)
        self.assertTrue(report.activation_satisfied)
        self.assertTrue(
            all(item.status is DryRunCheckStatus.PASS for item in report.operations)
        )
        self.assertEqual(report.to_dict(), report.to_dict())

    def test_forbidden_path_is_rejected(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        report = run_pilot_dry_run(
            current,
            preflight=passing_preflight(current),
            activation=activation,
            operations=(
                PilotDryRunOperation(
                    operation_id="modify-forbidden",
                    action=PilotAction.MODIFY_FILES,
                    path="src/secrets/token.py",
                ),
            ),
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.operations[0].status, DryRunCheckStatus.FAIL)

    def test_forbidden_action_is_rejected(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        report = run_pilot_dry_run(
            current,
            preflight=passing_preflight(current),
            activation=activation,
            operations=(
                PilotDryRunOperation(
                    operation_id="comment",
                    action=PilotAction.COMMENT,
                ),
            ),
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.operations[0].status, DryRunCheckStatus.FAIL)

    def test_missing_activation_blocks_every_operation(self) -> None:
        current = contract()
        report = run_pilot_dry_run(
            current,
            preflight=passing_preflight(current),
            activation=None,
            operations=(
                PilotDryRunOperation(
                    operation_id="read-source",
                    action=PilotAction.READ,
                    path="src/app.py",
                ),
                PilotDryRunOperation(
                    operation_id="validate",
                    action=PilotAction.RUN_VALIDATION,
                ),
            ),
        )

        self.assertFalse(report.passed)
        self.assertFalse(report.activation_satisfied)
        self.assertTrue(
            all(item.status is DryRunCheckStatus.FAIL for item in report.operations)
        )

    def test_failed_preflight_blocks_every_operation(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        preflight = run_pilot_preflight(
            current,
            observed_repository="owner/other-repo",
            observed_base_branch=current.target.base_branch,
            observed_baseline_sha=current.target.baseline_sha,
            provider_availability=(
                ProviderAvailabilitySnapshot(
                    provider_id="jules",
                    availability=ProviderAvailability.AVAILABLE,
                ),
            ),
            acceptance_command_readiness={"unit-tests": True},
        )
        report = run_pilot_dry_run(
            current,
            preflight=preflight,
            activation=activation,
            operations=(
                PilotDryRunOperation(
                    operation_id="read-source",
                    action=PilotAction.READ,
                    path="src/app.py",
                ),
            ),
        )

        self.assertFalse(report.passed)
        self.assertFalse(report.preflight_passed)
        self.assertEqual(report.operations[0].status, DryRunCheckStatus.FAIL)

    def test_path_scoped_action_requires_a_path(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        report = run_pilot_dry_run(
            current,
            preflight=passing_preflight(current),
            activation=activation,
            operations=(
                PilotDryRunOperation(
                    operation_id="read-without-path",
                    action=PilotAction.READ,
                ),
            ),
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.operations[0].status, DryRunCheckStatus.FAIL)

    def test_dry_run_never_modifies_target_fixture(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            sentinel = target / "sentinel.txt"
            sentinel.write_text("unchanged\n", encoding="utf-8")
            before = sentinel.read_bytes()

            report = run_pilot_dry_run(
                current,
                preflight=passing_preflight(current),
                activation=activation,
                operations=(
                    PilotDryRunOperation(
                        operation_id="modify-source",
                        action=PilotAction.MODIFY_FILES,
                        path="src/app.py",
                    ),
                ),
            )

            self.assertTrue(report.passed)
            self.assertEqual(sentinel.read_bytes(), before)
            self.assertEqual(
                sorted(path.name for path in target.iterdir()),
                ["sentinel.txt"],
            )

    def test_duplicate_operation_ids_are_rejected(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T14:00:00Z",
        )
        with self.assertRaises(ValueError):
            run_pilot_dry_run(
                current,
                preflight=passing_preflight(current),
                activation=activation,
                operations=(
                    PilotDryRunOperation(
                        operation_id="same",
                        action=PilotAction.RUN_VALIDATION,
                    ),
                    PilotDryRunOperation(
                        operation_id="same",
                        action=PilotAction.OPEN_PULL_REQUEST,
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
