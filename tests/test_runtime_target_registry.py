from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import unittest

from ade.runtime_target_registry import (
    RuntimeTargetKind,
    RuntimeTargetObservation,
    RuntimeTargetRegistration,
    RuntimeTargetSpec,
    TrustedRuntimeTargetRegistry,
)
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationError,
)


SHA = "a" * 40
NOW = datetime(2026, 9, 29, 23, 10, tzinfo=UTC)


def contract(environment: str = "repository") -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="target-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment=environment,
        required_probe_ids=("probe-a",),
        max_attempts=2,
        timeout_seconds=30,
    )


def registration(
    *,
    environment: str,
    kind: RuntimeTargetKind,
    implementation_id: str,
    observed_sha: str = SHA,
    observed_at: datetime = NOW,
    deployment_id: str | None = None,
) -> RuntimeTargetRegistration:
    def observer(_):
        return RuntimeTargetObservation(
            source_sha=observed_sha,
            observed_at=observed_at,
            deployment_id=deployment_id,
        )

    return RuntimeTargetRegistration(
        target_repository="example/target",
        spec=RuntimeTargetSpec(
            target_id=f"{environment}-runtime",
            environment=environment,
            kind=kind,
            max_age_seconds=300,
            max_future_skew_seconds=30,
        ),
        implementation_id=implementation_id,
        observer=observer,
    )


class RuntimeTargetRegistryTests(unittest.TestCase):
    def test_repository_runtime_is_source_bound_and_not_a_deployment(self) -> None:
        registry = TrustedRuntimeTargetRegistry(
            [
                registration(
                    environment="repository",
                    kind=RuntimeTargetKind.REPOSITORY,
                    implementation_id="trusted-merge-sha-v1",
                )
            ]
        )
        resolution = registry.resolve(contract(), now=NOW)
        evidence = resolution.evidence
        self.assertEqual(evidence.kind, RuntimeTargetKind.REPOSITORY)
        self.assertEqual(evidence.source_sha, SHA)
        self.assertIsNone(evidence.deployment_id)
        self.assertEqual(evidence.provenance_id, "trusted-merge-sha-v1")
        self.assertEqual(resolution.spec.deployment_required, False)

    def test_preview_staging_and_production_require_explicit_deployment_identity(self) -> None:
        kinds = (
            ("preview", RuntimeTargetKind.PREVIEW),
            ("staging", RuntimeTargetKind.STAGING),
            ("production", RuntimeTargetKind.PRODUCTION),
        )
        for environment, kind in kinds:
            with self.subTest(environment=environment):
                registry = TrustedRuntimeTargetRegistry(
                    [
                        registration(
                            environment=environment,
                            kind=kind,
                            implementation_id=f"{environment}-adapter-v1",
                            deployment_id=f"{environment}-dep-001",
                        )
                    ]
                )
                resolution = registry.resolve(contract(environment), now=NOW)
                self.assertEqual(resolution.evidence.kind, kind)
                self.assertEqual(
                    resolution.evidence.deployment_id,
                    f"{environment}-dep-001",
                )
                self.assertTrue(resolution.spec.deployment_required)

                missing = TrustedRuntimeTargetRegistry(
                    [
                        registration(
                            environment=environment,
                            kind=kind,
                            implementation_id=f"{environment}-adapter-v1",
                            deployment_id=None,
                        )
                    ]
                )
                with self.assertRaisesRegex(
                    RuntimeVerificationError,
                    "requires deployment_id",
                ):
                    missing.resolve(contract(environment), now=NOW)

    def test_source_sha_mismatch_fails_closed(self) -> None:
        registry = TrustedRuntimeTargetRegistry(
            [
                registration(
                    environment="repository",
                    kind=RuntimeTargetKind.REPOSITORY,
                    implementation_id="trusted-merge-sha-v1",
                    observed_sha="b" * 40,
                )
            ]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "source SHA"):
            registry.resolve(contract(), now=NOW)

    def test_stale_and_future_observations_fail_closed(self) -> None:
        stale = TrustedRuntimeTargetRegistry(
            [
                registration(
                    environment="repository",
                    kind=RuntimeTargetKind.REPOSITORY,
                    implementation_id="trusted-merge-sha-v1",
                    observed_at=NOW - timedelta(seconds=301),
                )
            ]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "stale"):
            stale.resolve(contract(), now=NOW)

        future = TrustedRuntimeTargetRegistry(
            [
                registration(
                    environment="repository",
                    kind=RuntimeTargetKind.REPOSITORY,
                    implementation_id="trusted-merge-sha-v1",
                    observed_at=NOW + timedelta(seconds=31),
                )
            ]
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "future"):
            future.resolve(contract(), now=NOW)

    def test_unknown_environment_and_duplicate_registration_fail_closed(self) -> None:
        item = registration(
            environment="repository",
            kind=RuntimeTargetKind.REPOSITORY,
            implementation_id="trusted-merge-sha-v1",
        )
        registry = TrustedRuntimeTargetRegistry([item])
        with self.assertRaisesRegex(RuntimeVerificationError, "no trusted"):
            registry.resolve(contract("production"), now=NOW)

        with self.assertRaisesRegex(RuntimeVerificationError, "duplicate"):
            TrustedRuntimeTargetRegistry([item, item])

    def test_provenance_is_controller_owned_and_ci_is_not_evidence(self) -> None:
        registry = TrustedRuntimeTargetRegistry(
            [
                registration(
                    environment="production",
                    kind=RuntimeTargetKind.PRODUCTION,
                    implementation_id="trusted-production-adapter-v9",
                    deployment_id="prod-dep-001",
                )
            ]
        )
        resolution = registry.resolve(contract("production"), now=NOW)
        payload = resolution.canonical_dict()
        raw = json.dumps(payload, sort_keys=True)
        self.assertEqual(
            resolution.evidence.provenance_id,
            "trusted-production-adapter-v9",
        )
        self.assertNotIn("ci", raw.casefold())
        self.assertNotIn("workflow", raw.casefold())
        self.assertNotIn("status_check", raw.casefold())

    def test_registry_fingerprint_is_order_independent(self) -> None:
        a = registration(
            environment="repository",
            kind=RuntimeTargetKind.REPOSITORY,
            implementation_id="repo-v1",
        )
        b = registration(
            environment="preview",
            kind=RuntimeTargetKind.PREVIEW,
            implementation_id="preview-v1",
            deployment_id="preview-dep",
        )
        first = TrustedRuntimeTargetRegistry([a, b])
        second = TrustedRuntimeTargetRegistry([b, a])
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())


if __name__ == "__main__":
    unittest.main()
