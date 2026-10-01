from __future__ import annotations

from dataclasses import replace
import unittest

from ade.accepted_plan import AcceptedPlan
from ade.campaign import AutonomousCampaign, CampaignStatus
from ade.development_plan import DevelopmentPlan, PlannedTask
from ade.release_candidate import ReleaseEnvironment
from ade.release_readiness import (
    ReleaseReadinessError,
    derive_release_readiness,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "8" * 40


def accepted_plan() -> AcceptedPlan:
    plan = DevelopmentPlan(
        goal="Ship a verified bounded improvement.",
        tasks=(
            PlannedTask(
                task_id="release-001",
                title="First bounded task",
                prompt="Implement the first bounded change.",
                depends_on=(),
                allowed_paths=("src/example.py",),
                acceptance=("First acceptance passes.",),
            ),
            PlannedTask(
                task_id="release-002",
                title="Second bounded task",
                prompt="Implement the second bounded change.",
                depends_on=("release-001",),
                allowed_paths=("tests/test_example.py",),
                acceptance=("Second acceptance passes.",),
            ),
        ),
    )
    return AcceptedPlan.accept(plan)


def campaign(
    *,
    status: CampaignStatus = CampaignStatus.COMPLETED,
    completed_task_ids: tuple[str, ...] = ("release-001", "release-002"),
    goal: str = "Ship a verified bounded improvement.",
    task_ids: tuple[str, ...] = ("release-001", "release-002"),
) -> AutonomousCampaign:
    return AutonomousCampaign(
        campaign_id="v1.8-release-campaign-001",
        goal=goal,
        task_ids=task_ids,
        status=status,
        completed_task_ids=completed_task_ids,
    )


def runtime_bundle(
    *,
    verification_id: str | None = None,
    receipt_status: str = "VERIFIED",
    task_id: str = "release-002",
    dispatch_count: int = 1,
    probe_status: RuntimeProbeStatus = RuntimeProbeStatus.PASS,
):
    verification_id = verification_id or f"rv-{SOURCE_SHA}"
    contract = RuntimeVerificationContract(
        verification_id=verification_id,
        target_repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        environment="repository",
        required_probe_ids=("production-import-smoke",),
    )
    report = evaluate_runtime_verification(
        contract,
        (
            RuntimeProbeResult(
                probe_id="production-import-smoke",
                status=probe_status,
                source_sha=SOURCE_SHA,
            ),
        ),
    )
    receipt = RuntimeVerificationReceipt(
        verification_id=verification_id,
        task_id=task_id,
        target_repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        contract_fingerprint=contract.fingerprint(),
        registry_fingerprint="a" * 64,
        policy_fingerprint="b" * 64,
        status=receipt_status,
        dispatch_count=dispatch_count,
    )
    return contract, receipt, report


class ReleaseReadinessTests(unittest.TestCase):
    def test_verified_terminal_campaign_derives_release_candidate(self) -> None:
        contract, receipt, report = runtime_bundle()
        first = derive_release_readiness(
            accepted_plan=accepted_plan(),
            campaign=campaign(),
            runtime_contract=contract,
            runtime_receipt=receipt,
            runtime_report=report,
            target_environment=ReleaseEnvironment.STAGING,
        )
        second = derive_release_readiness(
            accepted_plan=accepted_plan(),
            campaign=campaign(),
            runtime_contract=contract,
            runtime_receipt=receipt,
            runtime_report=report,
            target_environment=ReleaseEnvironment.STAGING,
        )

        self.assertEqual(first, second)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(first.candidate.repository, REPOSITORY)
        self.assertEqual(first.candidate.source_sha, SOURCE_SHA)
        self.assertEqual(
            first.candidate.runtime_verification_id,
            f"rv-{SOURCE_SHA}",
        )
        self.assertEqual(
            first.candidate.target_environment,
            ReleaseEnvironment.STAGING,
        )
        self.assertTrue(first.candidate.requires_human_approval)
        self.assertEqual(
            [ref.path for ref in first.candidate.evidence_refs],
            [
                ".autodev/accepted-plan.json",
                ".autodev/campaign.json",
                ".autodev/runtime-verification/release-002/report.json",
            ],
        )
        payload = first.canonical_dict()
        self.assertTrue(payload["derived_by_trusted_controller"])
        self.assertFalse(payload["deployment_authority"])
        self.assertFalse(payload["promotion_authority"])
        self.assertFalse(payload["auto_promote"])

    def test_campaign_must_be_terminal_complete(self) -> None:
        contract, receipt, report = runtime_bundle()
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "terminal COMPLETED Campaign",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(status=CampaignStatus.RUNNING),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=report,
                target_environment=ReleaseEnvironment.PREVIEW,
            )

        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "every Campaign task completed",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(
                    completed_task_ids=("release-001",),
                ),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=report,
                target_environment=ReleaseEnvironment.PREVIEW,
            )

    def test_campaign_must_match_accepted_plan(self) -> None:
        contract, receipt, report = runtime_bundle()
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "goal does not match AcceptedPlan",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(goal="Different goal."),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=report,
                target_environment=ReleaseEnvironment.STAGING,
            )

        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "tasks do not match AcceptedPlan",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(
                    task_ids=("release-002", "release-001"),
                    completed_task_ids=("release-002", "release-001"),
                ),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=report,
                target_environment=ReleaseEnvironment.STAGING,
            )

    def test_runtime_verification_must_be_exact_post_merge_identity(self) -> None:
        contract, receipt, report = runtime_bundle(
            verification_id="rv-arbitrary"
        )
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "exact post-merge identity",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=report,
                target_environment=ReleaseEnvironment.PRODUCTION,
            )

    def test_runtime_receipt_must_be_verified_dispatched_and_final_task_bound(self) -> None:
        for kwargs, message in (
            ({"receipt_status": "FAILED"}, "receipt must be VERIFIED"),
            ({"dispatch_count": 0}, "was never dispatched"),
            ({"task_id": "release-001"}, "final completed Campaign task"),
        ):
            with self.subTest(kwargs=kwargs):
                contract, receipt, report = runtime_bundle(**kwargs)
                with self.assertRaisesRegex(
                    ReleaseReadinessError,
                    message,
                ):
                    derive_release_readiness(
                        accepted_plan=accepted_plan(),
                        campaign=campaign(),
                        runtime_contract=contract,
                        runtime_receipt=receipt,
                        runtime_report=report,
                        target_environment=ReleaseEnvironment.STAGING,
                    )

    def test_runtime_report_must_be_verified_and_exactly_bound(self) -> None:
        contract, receipt, failed_report = runtime_bundle(
            probe_status=RuntimeProbeStatus.FAIL
        )
        receipt = replace(receipt, status="VERIFIED")
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "report must be VERIFIED",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(),
                runtime_contract=contract,
                runtime_receipt=receipt,
                runtime_report=failed_report,
                target_environment=ReleaseEnvironment.STAGING,
            )

        good_contract, good_receipt, good_report = runtime_bundle()
        drifted_report = replace(good_report, source_sha="9" * 40)
        with self.assertRaisesRegex(
            ReleaseReadinessError,
            "report source SHA drift",
        ):
            derive_release_readiness(
                accepted_plan=accepted_plan(),
                campaign=campaign(),
                runtime_contract=good_contract,
                runtime_receipt=good_receipt,
                runtime_report=drifted_report,
                target_environment=ReleaseEnvironment.STAGING,
            )


if __name__ == "__main__":
    unittest.main()
