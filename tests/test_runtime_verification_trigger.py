from __future__ import annotations

import unittest

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationDisposition,
    RuntimeVerificationError,
    RuntimeVerificationReport,
    evaluate_runtime_verification,
)
from ade.runtime_verification_trigger import (
    RuntimeVerificationPolicy,
    RuntimeVerificationReceipt,
    arm_post_merge_runtime_verification,
    record_runtime_verification_dispatch,
    record_runtime_verification_report,
    runtime_verification_report_path,
)


SHA_A = "a" * 40
SHA_B = "b" * 40


def registry() -> TrustedRuntimeProbeRegistry:
    def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

    return TrustedRuntimeProbeRegistry(
        [
            RuntimeProbeRegistration(
                "offline-cli-smoke",
                "offline-cli-smoke-v1",
                passed,
            ),
            RuntimeProbeRegistration(
                "production-import-smoke",
                "production-import-smoke-v1",
                passed,
            ),
        ]
    )


def policy() -> RuntimeVerificationPolicy:
    return RuntimeVerificationPolicy(
        target_repository="example/target",
        environment="production",
        required_probe_ids=(
            "production-import-smoke",
            "offline-cli-smoke",
        ),
        max_attempts=2,
        timeout_seconds=300,
    )


class RuntimeVerificationTriggerTests(unittest.TestCase):
    def test_first_trusted_merge_arms_exact_sha_contract(self) -> None:
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        self.assertTrue(activation.should_dispatch)
        self.assertEqual(activation.contract.source_sha, SHA_A)
        self.assertEqual(activation.receipt.source_sha, SHA_A)
        self.assertEqual(activation.receipt.task_id, "task-001")
        self.assertEqual(activation.receipt.status, "ARMED")
        self.assertEqual(activation.receipt.dispatch_count, 0)
        self.assertEqual(
            activation.receipt.contract_fingerprint,
            activation.contract.fingerprint(),
        )

    def test_armed_receipt_remains_retryable_until_dispatch_acknowledgement(self) -> None:
        first = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        second = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
            existing_receipt=first.receipt,
        )
        self.assertTrue(second.should_dispatch)
        self.assertEqual(second.receipt, first.receipt)

    def test_dispatched_same_identity_receipt_suppresses_replay(self) -> None:
        first = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        dispatched = record_runtime_verification_dispatch(
            contract=first.contract,
            registry=registry(),
            receipt=first.receipt,
        ).receipt
        replay = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
            existing_receipt=dispatched,
        )
        self.assertFalse(replay.should_dispatch)
        self.assertEqual(replay.receipt.status, "DISPATCHED")

    def test_terminal_same_identity_receipt_also_suppresses_replay(self) -> None:
        first = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        verified = RuntimeVerificationReceipt(
            **{
                **first.receipt.canonical_dict(),
                "status": "VERIFIED",
                "dispatch_count": 1,
            }
        )
        replay = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
            existing_receipt=verified,
        )
        self.assertFalse(replay.should_dispatch)
        self.assertEqual(replay.receipt.status, "VERIFIED")

    def test_new_merge_sha_is_not_suppressed_by_stale_receipt(self) -> None:
        first = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        next_activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-002",
            target_repository="example/target",
            trusted_merge_sha=SHA_B,
            existing_receipt=first.receipt,
        )
        self.assertTrue(next_activation.should_dispatch)
        self.assertEqual(next_activation.contract.source_sha, SHA_B)
        self.assertNotEqual(
            next_activation.receipt.verification_id,
            first.receipt.verification_id,
        )

    def test_wrong_repository_and_unregistered_probe_fail_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeVerificationError, "does not match"):
            arm_post_merge_runtime_verification(
                policy=policy(),
                registry=registry(),
                task_id="task-001",
                target_repository="other/target",
                trusted_merge_sha=SHA_A,
            )

        unsupported = RuntimeVerificationPolicy(
            target_repository="example/target",
            environment="production",
            required_probe_ids=("unknown-probe",),
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "unregistered"):
            arm_post_merge_runtime_verification(
                policy=unsupported,
                registry=registry(),
                task_id="task-001",
                target_repository="example/target",
                trusted_merge_sha=SHA_A,
            )

    def test_policy_and_receipt_round_trip_strictly(self) -> None:
        original_policy = policy()
        loaded_policy = RuntimeVerificationPolicy.from_dict(
            original_policy.canonical_dict()
        )
        self.assertEqual(loaded_policy, original_policy)
        self.assertEqual(loaded_policy.fingerprint(), original_policy.fingerprint())

        activation = arm_post_merge_runtime_verification(
            policy=original_policy,
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        loaded_receipt = RuntimeVerificationReceipt.from_dict(
            activation.receipt.canonical_dict()
        )
        self.assertEqual(loaded_receipt, activation.receipt)

    def test_dispatch_transition_is_exactly_once(self) -> None:
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        first = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=registry(),
            receipt=activation.receipt,
        )
        self.assertTrue(first.changed)
        self.assertEqual(first.receipt.status, "DISPATCHED")
        self.assertEqual(first.receipt.dispatch_count, 1)

        replay = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=registry(),
            receipt=first.receipt,
        )
        self.assertFalse(replay.changed)
        self.assertEqual(replay.receipt, first.receipt)

    def test_dispatch_rejects_contract_or_registry_drift(self) -> None:
        trusted_registry = registry()
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=trusted_registry,
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        stale_contract = type(activation.contract)(
            verification_id=f"rv-{SHA_B}",
            target_repository="example/target",
            source_sha=SHA_B,
            environment="production",
            required_probe_ids=activation.contract.required_probe_ids,
            max_attempts=2,
            timeout_seconds=300,
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "id drift|source SHA drift"):
            record_runtime_verification_dispatch(
                contract=stale_contract,
                registry=trusted_registry,
                receipt=activation.receipt,
            )

        def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        drifted_registry = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    "offline-cli-smoke",
                    "offline-cli-smoke-v2",
                    passed,
                ),
                RuntimeProbeRegistration(
                    "production-import-smoke",
                    "production-import-smoke-v1",
                    passed,
                ),
            ]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "registry drift"):
            record_runtime_verification_dispatch(
                contract=activation.contract,
                registry=drifted_registry,
                receipt=activation.receipt,
            )

    def test_dispatched_receipt_completes_from_verified_report(self) -> None:
        trusted_registry = registry()
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=trusted_registry,
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        dispatched = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=trusted_registry,
            receipt=activation.receipt,
        ).receipt
        report = evaluate_runtime_verification(
            activation.contract,
            [
                RuntimeProbeResult(
                    probe_id=probe_id,
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SHA_A,
                )
                for probe_id in activation.contract.required_probe_ids
            ],
        )
        self.assertEqual(
            report.disposition,
            RuntimeVerificationDisposition.VERIFIED,
        )
        completion = record_runtime_verification_report(
            contract=activation.contract,
            receipt=dispatched,
            report=report,
        )
        self.assertTrue(completion.changed)
        self.assertEqual(completion.receipt.status, "VERIFIED")
        self.assertEqual(completion.receipt.dispatch_count, 1)

        replay = record_runtime_verification_report(
            contract=activation.contract,
            receipt=completion.receipt,
            report=report,
        )
        self.assertFalse(replay.changed)
        self.assertEqual(replay.receipt, completion.receipt)

    def test_failed_report_marks_receipt_failed(self) -> None:
        trusted_registry = registry()
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=trusted_registry,
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        dispatched = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=trusted_registry,
            receipt=activation.receipt,
        ).receipt
        results = []
        for index, probe_id in enumerate(activation.contract.required_probe_ids):
            results.append(
                RuntimeProbeResult(
                    probe_id=probe_id,
                    status=(
                        RuntimeProbeStatus.FAIL
                        if index == 0
                        else RuntimeProbeStatus.PASS
                    ),
                    source_sha=SHA_A,
                )
            )
        report = evaluate_runtime_verification(
            activation.contract,
            results,
        )
        completion = record_runtime_verification_report(
            contract=activation.contract,
            receipt=dispatched,
            report=report,
        )
        self.assertTrue(completion.changed)
        self.assertEqual(completion.receipt.status, "FAILED")

    def test_stale_runtime_report_is_rejected(self) -> None:
        trusted_registry = registry()
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=trusted_registry,
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        dispatched = record_runtime_verification_dispatch(
            contract=activation.contract,
            registry=trusted_registry,
            receipt=activation.receipt,
        ).receipt
        stale = RuntimeVerificationReport(
            verification_id=activation.contract.verification_id,
            contract_fingerprint=activation.contract.fingerprint(),
            source_sha=SHA_B,
            disposition=RuntimeVerificationDisposition.FAILED,
            results=(),
            missing_probe_ids=(),
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "source SHA drift"):
            record_runtime_verification_report(
                contract=activation.contract,
                receipt=dispatched,
                report=stale,
            )

    def test_report_path_is_task_scoped(self) -> None:
        self.assertEqual(
            runtime_verification_report_path("task-001"),
            ".autodev/runtime-verification/task-001/report.json",
        )

    def test_receipt_contains_no_executable_or_secret_payload_surface(self) -> None:
        activation = arm_post_merge_runtime_verification(
            policy=policy(),
            registry=registry(),
            task_id="task-001",
            target_repository="example/target",
            trusted_merge_sha=SHA_A,
        )
        payload = activation.receipt.canonical_dict()
        self.assertNotIn("command", payload)
        self.assertNotIn("url", payload)
        self.assertNotIn("headers", payload)
        self.assertNotIn("credentials", payload)


if __name__ == "__main__":
    unittest.main()
