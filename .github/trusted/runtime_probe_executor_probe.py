from __future__ import annotations

import json
import os
import time

from ade.runtime_probe_executor import execute_runtime_verification_bounded
from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
)


SHA = "a" * 40


def _pass(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    clean = (
        invocation.credential_authority is False
        and invocation.network_authority is False
        and invocation.deployment_authority is False
        and "GITHUB_TOKEN" not in os.environ
    )
    return RuntimeProbeObservation(
        RuntimeProbeStatus.PASS if clean else RuntimeProbeStatus.FAIL,
        detail_code="clean-authority" if clean else "authority-expanded",
    )


def _retry(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    if invocation.attempt == 1:
        return RuntimeProbeObservation(
            RuntimeProbeStatus.ERROR,
            detail_code="transient-error",
        )
    return RuntimeProbeObservation(
        RuntimeProbeStatus.PASS,
        detail_code="retry-passed",
    )


def _timeout(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    time.sleep(5)
    return RuntimeProbeObservation(RuntimeProbeStatus.PASS)


def main() -> int:
    old = os.environ.get("GITHUB_TOKEN")
    os.environ["GITHUB_TOKEN"] = "must-not-reach-probe"
    try:
        registry = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration("probe-a", "probe-a-v1", _pass),
                RuntimeProbeRegistration("probe-b", "probe-b-v1", _retry),
            ]
        )
        contract = RuntimeVerificationContract(
            verification_id="bounded-runtime-proof",
            target_repository="example/target",
            source_sha=SHA,
            environment="repository",
            required_probe_ids=("probe-a", "probe-b"),
            max_attempts=2,
            timeout_seconds=1,
        )
        execution = execute_runtime_verification_bounded(contract, registry)
    finally:
        if old is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = old

    assert execution.report.disposition is RuntimeVerificationDisposition.VERIFIED
    assert execution.attempts_by_probe == (("probe-a", 1), ("probe-b", 2))
    assert execution.report.results[0].detail_code == "clean-authority"
    assert execution.report.results[1].attempt == 2

    timeout_registry = TrustedRuntimeProbeRegistry(
        [RuntimeProbeRegistration("timeout-probe", "timeout-v1", _timeout)]
    )
    timeout_contract = RuntimeVerificationContract(
        verification_id="timeout-runtime-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("timeout-probe",),
        max_attempts=1,
        timeout_seconds=1,
    )
    started = time.monotonic()
    timeout_execution = execute_runtime_verification_bounded(
        timeout_contract,
        timeout_registry,
    )
    elapsed = time.monotonic() - started
    assert elapsed < 4
    assert (
        timeout_execution.report.disposition
        is RuntimeVerificationDisposition.FAILED
    )
    assert timeout_execution.report.results[0].detail_code == "probe-timeout"

    print(json.dumps({
        "ok": True,
        "hard_timeout_enforced": True,
        "error_retry_bounded": True,
        "attempt_budget_enforced": True,
        "credentials_removed": True,
        "network_authority_not_granted": True,
        "deployment_authority_not_granted": True,
        "verified_report_fingerprint": execution.report.fingerprint(),
        "timeout_report_fingerprint": timeout_execution.report.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
