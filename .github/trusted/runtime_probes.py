from __future__ import annotations

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus
from ade.runtime_verification_trigger import RuntimeVerificationPolicy


def _execution_not_enabled(
    _: RuntimeProbeInvocation,
) -> RuntimeProbeObservation:
    # Slice 003 only arms and dispatches verification. Actual bounded probe
    # execution is intentionally introduced in Slice 004.
    return RuntimeProbeObservation(
        RuntimeProbeStatus.ERROR,
        detail_code="execution-not-enabled",
    )


def build_runtime_probe_registry() -> TrustedRuntimeProbeRegistry:
    return TrustedRuntimeProbeRegistry(
        [
            RuntimeProbeRegistration(
                probe_id="offline-cli-smoke",
                implementation_id="offline-cli-smoke-v1",
                runner=_execution_not_enabled,
            ),
            RuntimeProbeRegistration(
                probe_id="production-import-smoke",
                implementation_id="production-import-smoke-v1",
                runner=_execution_not_enabled,
            ),
        ]
    )


def build_runtime_verification_policy(
    target_repository: str,
) -> RuntimeVerificationPolicy:
    return RuntimeVerificationPolicy(
        target_repository=target_repository,
        environment="repository",
        required_probe_ids=(
            "offline-cli-smoke",
            "production-import-smoke",
        ),
        max_attempts=2,
        timeout_seconds=300,
    )
