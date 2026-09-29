from __future__ import annotations

import unittest

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus, RuntimeVerificationError
from ade.runtime_verification_trigger import (
    RuntimeVerificationPolicy,
    RuntimeVerificationReceipt,
    arm_post_merge_runtime_verification,
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

    def test_same_receipt_suppresses_duplicate_dispatch(self) -> None:
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
        self.assertFalse(second.should_dispatch)
        self.assertEqual(second.receipt, first.receipt)

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
