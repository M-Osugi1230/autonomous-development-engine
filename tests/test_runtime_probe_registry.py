from __future__ import annotations

import unittest

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationError,
)


SHA = "a" * 40


def contract(*probe_ids: str) -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="registry-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment="production",
        required_probe_ids=probe_ids or ("probe-a",),
        max_attempts=2,
    )


class RuntimeProbeRegistryTests(unittest.TestCase):
    def test_registry_fingerprint_is_order_independent(self) -> None:
        def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        first = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration("probe-b", "impl-b-v1", passed),
                RuntimeProbeRegistration("probe-a", "impl-a-v1", passed),
            ]
        )
        second = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration("probe-a", "impl-a-v1", passed),
                RuntimeProbeRegistration("probe-b", "impl-b-v1", passed),
            ]
        )
        self.assertEqual(first.probe_ids, ("probe-a", "probe-b"))
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_unknown_contract_probe_fails_before_runner_execution(self) -> None:
        calls: list[RuntimeProbeInvocation] = []

        def runner(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            calls.append(invocation)
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", runner)]
        )
        with self.assertRaisesRegex(
            RuntimeVerificationError,
            "unregistered runtime probes",
        ):
            registry.execute(contract("probe-a", "probe-b"), probe_id="probe-a")
        self.assertEqual(calls, [])

    def test_registry_binds_identity_and_source_sha(self) -> None:
        seen: list[RuntimeProbeInvocation] = []

        def runner(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            seen.append(invocation)
            return RuntimeProbeObservation(
                RuntimeProbeStatus.PASS,
                detail_code="healthy",
            )

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", runner)]
        )
        result = registry.execute(contract("probe-a"), probe_id="probe-a", attempt=2)
        self.assertEqual(result.probe_id, "probe-a")
        self.assertEqual(result.source_sha, SHA)
        self.assertEqual(result.attempt, 2)
        self.assertEqual(result.status, RuntimeProbeStatus.PASS)
        self.assertEqual(result.detail_code, "healthy")
        self.assertEqual(
            seen,
            [
                RuntimeProbeInvocation(
                    target_repository="example/target",
                    source_sha=SHA,
                    environment="production",
                    attempt=2,
                    timeout_seconds=300,
                    repository_write_authority=False,
                    credential_authority=False,
                    network_authority=False,
                    deployment_authority=False,
                )
            ],
        )

    def test_registry_never_grants_runtime_authority(self) -> None:
        seen: list[RuntimeProbeInvocation] = []

        def runner(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            seen.append(invocation)
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", runner)]
        )
        custom = RuntimeVerificationContract(
            verification_id="authority-proof",
            target_repository="example/target",
            source_sha=SHA,
            environment="repository",
            required_probe_ids=("probe-a",),
            max_attempts=2,
            timeout_seconds=17,
        )
        registry.execute(custom, probe_id="probe-a", attempt=2)
        self.assertEqual(len(seen), 1)
        invocation = seen[0]
        self.assertEqual(invocation.attempt, 2)
        self.assertEqual(invocation.timeout_seconds, 17)
        self.assertFalse(invocation.repository_write_authority)
        self.assertFalse(invocation.credential_authority)
        self.assertFalse(invocation.network_authority)
        self.assertFalse(invocation.deployment_authority)

    def test_probe_not_required_by_contract_is_rejected(self) -> None:
        def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        registry = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration("probe-a", "impl-a-v1", passed),
                RuntimeProbeRegistration("probe-b", "impl-b-v1", passed),
            ]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "not required"):
            registry.execute(contract("probe-a"), probe_id="probe-b")

    def test_attempt_budget_is_enforced_before_execution(self) -> None:
        called = False

        def runner(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            nonlocal called
            called = True
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", runner)]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "attempt"):
            registry.execute(contract("probe-a"), probe_id="probe-a", attempt=3)
        self.assertFalse(called)

    def test_runner_exception_becomes_secret_free_error_observation(self) -> None:
        def broken(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            raise RuntimeError("token=super-secret-runtime-value")

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", broken)]
        )
        result = registry.execute(contract("probe-a"), probe_id="probe-a")
        self.assertEqual(result.status, RuntimeProbeStatus.ERROR)
        self.assertEqual(result.detail_code, "runner-exception")
        self.assertNotIn(
            "super-secret-runtime-value",
            str(result.canonical_dict()),
        )

    def test_invalid_runner_output_fails_closed(self) -> None:
        def invalid(_: RuntimeProbeInvocation):
            return {"status": "PASS"}

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", invalid)]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "invalid observation"):
            registry.execute(contract("probe-a"), probe_id="probe-a")

    def test_duplicate_probe_ids_are_rejected(self) -> None:
        def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        with self.assertRaisesRegex(RuntimeVerificationError, "duplicate"):
            TrustedRuntimeProbeRegistry(
                [
                    RuntimeProbeRegistration("probe-a", "impl-a-v1", passed),
                    RuntimeProbeRegistration("probe-a", "impl-a-v2", passed),
                ]
            )

    def test_registry_metadata_contains_no_runner_payload(self) -> None:
        def passed(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
            return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "impl-a-v1", passed)]
        )
        self.assertEqual(
            registry.canonical_dict(),
            {
                "schema_version": 1,
                "registrations": [
                    {
                        "probe_id": "probe-a",
                        "implementation_id": "impl-a-v1",
                    }
                ],
            },
        )


if __name__ == "__main__":
    unittest.main()
