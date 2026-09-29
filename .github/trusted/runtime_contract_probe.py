from __future__ import annotations

import json

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationError,
    evaluate_runtime_verification,
)


SHA = "a" * 40


def main() -> int:
    contract = RuntimeVerificationContract(
        verification_id="runtime-contract-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment="test",
        required_probe_ids=("probe-a", "probe-b"),
        max_attempts=2,
    )

    calls: list[RuntimeProbeInvocation] = []

    def pass_probe(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        calls.append(invocation)
        return RuntimeProbeObservation(RuntimeProbeStatus.PASS)

    registry = TrustedRuntimeProbeRegistry(
        [
            RuntimeProbeRegistration("probe-a", "impl-a-v1", pass_probe),
            RuntimeProbeRegistration("probe-b", "impl-b-v1", pass_probe),
        ]
    )
    registry.ensure_contract_supported(contract)
    result_a = registry.execute(contract, probe_id="probe-a")
    result_b = registry.execute(contract, probe_id="probe-b")
    assert result_a.probe_id == "probe-a"
    assert result_a.source_sha == SHA
    assert result_b.probe_id == "probe-b"
    assert result_b.source_sha == SHA
    assert len(calls) == 2

    partial = evaluate_runtime_verification(
        contract,
        [
            RuntimeProbeResult(
                probe_id="probe-a",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
            )
        ],
    )
    assert partial.disposition is RuntimeVerificationDisposition.PENDING

    complete = evaluate_runtime_verification(
        contract,
        [result_a, result_b],
    )
    assert complete.disposition is RuntimeVerificationDisposition.VERIFIED

    blocked = evaluate_runtime_verification(
        contract,
        [
            RuntimeProbeResult(
                probe_id="probe-a",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
            ),
            RuntimeProbeResult(
                probe_id="probe-b",
                status=RuntimeProbeStatus.FAIL,
                source_sha=SHA,
                detail_code="probe-failed",
            ),
        ],
    )
    assert blocked.disposition is RuntimeVerificationDisposition.FAILED

    stale_rejected = False
    try:
        evaluate_runtime_verification(
            contract,
            [
                RuntimeProbeResult(
                    probe_id="probe-a",
                    status=RuntimeProbeStatus.PASS,
                    source_sha="b" * 40,
                )
            ],
        )
    except RuntimeVerificationError:
        stale_rejected = True
    assert stale_rejected

    print(json.dumps({
        "ok": True,
        "partial_pending": True,
        "all_required_pass_verified": True,
        "required_failure_blocks": True,
        "stale_source_rejected": True,
        "trusted_registry_required": True,
        "registry_identity_binding": True,
        "registry_fingerprint": registry.fingerprint(),
        "contract_fingerprint": contract.fingerprint(),
        "report_fingerprint": complete.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
