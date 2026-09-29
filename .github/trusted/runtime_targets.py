from __future__ import annotations

from datetime import UTC, datetime

from ade.runtime_target_registry import (
    RuntimeTargetInvocation,
    RuntimeTargetKind,
    RuntimeTargetObservation,
    RuntimeTargetRegistration,
    RuntimeTargetSpec,
    TrustedRuntimeTargetRegistry,
)


def _repository_runtime(
    invocation: RuntimeTargetInvocation,
) -> RuntimeTargetObservation:
    # The exact source SHA originates from the trusted post-merge contract.
    # Repository runtime does not imply a deployment.
    return RuntimeTargetObservation(
        source_sha=invocation.source_sha,
        observed_at=datetime.now(UTC),
        deployment_id=None,
    )


def _deployment_observation_not_configured(
    _: RuntimeTargetInvocation,
) -> RuntimeTargetObservation:
    # Slice 005 deliberately refuses to infer preview/staging/production
    # deployment success from CI success. A later trusted deployment adapter
    # must supply explicit source-bound deployment evidence.
    raise RuntimeError("deployment observation not configured")


def build_runtime_target_registry(
    target_repository: str,
) -> TrustedRuntimeTargetRegistry:
    return TrustedRuntimeTargetRegistry(
        [
            RuntimeTargetRegistration(
                target_repository=target_repository,
                spec=RuntimeTargetSpec(
                    target_id="repository-runtime",
                    environment="repository",
                    kind=RuntimeTargetKind.REPOSITORY,
                    max_age_seconds=300,
                ),
                implementation_id="trusted-merge-sha-v1",
                observer=_repository_runtime,
            ),
            RuntimeTargetRegistration(
                target_repository=target_repository,
                spec=RuntimeTargetSpec(
                    target_id="preview-runtime",
                    environment="preview",
                    kind=RuntimeTargetKind.PREVIEW,
                    max_age_seconds=900,
                ),
                implementation_id="preview-deployment-adapter-v1",
                observer=_deployment_observation_not_configured,
            ),
            RuntimeTargetRegistration(
                target_repository=target_repository,
                spec=RuntimeTargetSpec(
                    target_id="staging-runtime",
                    environment="staging",
                    kind=RuntimeTargetKind.STAGING,
                    max_age_seconds=900,
                ),
                implementation_id="staging-deployment-adapter-v1",
                observer=_deployment_observation_not_configured,
            ),
            RuntimeTargetRegistration(
                target_repository=target_repository,
                spec=RuntimeTargetSpec(
                    target_id="production-runtime",
                    environment="production",
                    kind=RuntimeTargetKind.PRODUCTION,
                    max_age_seconds=900,
                ),
                implementation_id="production-deployment-adapter-v1",
                observer=_deployment_observation_not_configured,
            ),
        ]
    )
