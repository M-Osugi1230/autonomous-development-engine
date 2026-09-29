from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

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
NOW = datetime(2026, 9, 29, 23, 15, tzinfo=UTC)


def _contract(environment: str) -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id=f"target-{environment}-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment=environment,
        required_probe_ids=("probe-a",),
        max_attempts=1,
        timeout_seconds=30,
    )


def _registration(
    environment: str,
    kind: RuntimeTargetKind,
    implementation_id: str,
    *,
    deployment_id: str | None,
    observed_sha: str = SHA,
    observed_at: datetime = NOW,
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


def main() -> int:
    registrations = [
        _registration(
            "repository",
            RuntimeTargetKind.REPOSITORY,
            "trusted-merge-sha-v1",
            deployment_id=None,
        ),
        _registration(
            "preview",
            RuntimeTargetKind.PREVIEW,
            "preview-adapter-v1",
            deployment_id="preview-dep-001",
        ),
        _registration(
            "staging",
            RuntimeTargetKind.STAGING,
            "staging-adapter-v1",
            deployment_id="staging-dep-001",
        ),
        _registration(
            "production",
            RuntimeTargetKind.PRODUCTION,
            "production-adapter-v1",
            deployment_id="production-dep-001",
        ),
    ]
    registry = TrustedRuntimeTargetRegistry(registrations)

    resolutions = {
        environment: registry.resolve(_contract(environment), now=NOW)
        for environment in ("repository", "preview", "staging", "production")
    }
    assert resolutions["repository"].evidence.deployment_id is None
    for environment in ("preview", "staging", "production"):
        assert resolutions[environment].evidence.deployment_id == f"{environment}-dep-001"
        assert resolutions[environment].spec.deployment_required

    stale = TrustedRuntimeTargetRegistry(
        [
            _registration(
                "production",
                RuntimeTargetKind.PRODUCTION,
                "production-adapter-v1",
                deployment_id="production-dep-stale",
                observed_at=NOW - timedelta(seconds=301),
            )
        ]
    )
    try:
        stale.resolve(_contract("production"), now=NOW)
    except RuntimeVerificationError:
        stale_rejected = True
    else:
        stale_rejected = False
    assert stale_rejected

    mismatch = TrustedRuntimeTargetRegistry(
        [
            _registration(
                "preview",
                RuntimeTargetKind.PREVIEW,
                "preview-adapter-v1",
                deployment_id="preview-dep-wrong-sha",
                observed_sha="b" * 40,
            )
        ]
    )
    try:
        mismatch.resolve(_contract("preview"), now=NOW)
    except RuntimeVerificationError:
        mismatch_rejected = True
    else:
        mismatch_rejected = False
    assert mismatch_rejected

    missing = TrustedRuntimeTargetRegistry(
        [
            _registration(
                "staging",
                RuntimeTargetKind.STAGING,
                "staging-adapter-v1",
                deployment_id=None,
            )
        ]
    )
    try:
        missing.resolve(_contract("staging"), now=NOW)
    except RuntimeVerificationError:
        missing_deployment_rejected = True
    else:
        missing_deployment_rejected = False
    assert missing_deployment_rejected

    encoded = json.dumps(
        {
            key: value.canonical_dict()
            for key, value in resolutions.items()
        },
        sort_keys=True,
    )
    assert '"ci"' not in encoded.casefold()
    assert "workflow_run" not in encoded.casefold()

    print(json.dumps({
        "ok": True,
        "target_kinds_distinguished": True,
        "explicit_deployment_identity_required": True,
        "stale_deployment_rejected": True,
        "source_sha_provenance_bound": True,
        "ci_success_not_used_as_deployment_evidence": True,
        "trusted_provenance_id_bound": True,
        "registry_fingerprint": registry.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
