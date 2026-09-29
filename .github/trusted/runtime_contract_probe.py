from __future__ import annotations

import json

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
        [
            RuntimeProbeResult(
                probe_id="probe-a",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
            ),
            RuntimeProbeResult(
                probe_id="probe-b",
                status=RuntimeProbeStatus.PASS,
                source_sha=SHA,
            ),
        ],
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
        "contract_fingerprint": contract.fingerprint(),
        "report_fingerprint": complete.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
