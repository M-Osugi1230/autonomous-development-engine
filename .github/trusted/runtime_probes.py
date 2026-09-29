from __future__ import annotations

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus


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
