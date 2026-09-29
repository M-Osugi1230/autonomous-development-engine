from __future__ import annotations

import unittest

from ade.runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    RuntimeVerificationError,
    evaluate_runtime_verification,
)


SHA = "a" * 40


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="runtime-proof-001",
        target_repository="example/target",
        source_sha=SHA,
        environment="production",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )


class RuntimeVerificationTests(unittest.TestCase):
    def test_contract_is_deterministic_and_order_independent(self) -> None:
        first = contract()
        second = RuntimeVerificationContract(
            verification_id="runtime-proof-001",
            target_repository="example/target",
            source_sha=SHA,
            environment="production",
            required_probe_ids=("production-import-smoke", "offline-cli-smoke"),
            max_attempts=2,
            timeout_seconds=300,
        )
        self.assertEqual(first.required_probe_ids, second.required_probe_ids)
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_partial_results_are_pending(self) -> None:
        report = evaluate_runtime_verification(
            contract(),
            [
                RuntimeProbeResult(
                    probe_id="production-import-smoke",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SHA,
                )
            ],
        )
        self.assertEqual(report.disposition, RuntimeVerificationDisposition.PENDING)
        self.assertEqual(report.missing_probe_ids, ("offline-cli-smoke",))

    def test_all_required_pass_is_verified(self) -> None:
        report = evaluate_runtime_verification(
            contract(),
            [
                RuntimeProbeResult(
                    probe_id="production-import-smoke",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SHA,
                ),
                RuntimeProbeResult(
                    probe_id="offline-cli-smoke",
                    status=RuntimeProbeStatus.PASS,
                    source_sha=SHA,
                    attempt=2,
                ),
            ],
        )
        self.assertEqual(report.disposition, RuntimeVerificationDisposition.VERIFIED)
        self.assertEqual(report.missing_probe_ids, ())
        self.assertEqual(
            [result.probe_id for result in report.results],
            ["offline-cli-smoke", "production-import-smoke"],
        )

    def test_fail_error_or_skipped_required_probe_fails(self) -> None:
        for status in (
            RuntimeProbeStatus.FAIL,
            RuntimeProbeStatus.ERROR,
            RuntimeProbeStatus.SKIPPED,
        ):
            with self.subTest(status=status):
                report = evaluate_runtime_verification(
                    contract(),
                    [
                        RuntimeProbeResult(
                            probe_id="production-import-smoke",
                            status=RuntimeProbeStatus.PASS,
                            source_sha=SHA,
                        ),
                        RuntimeProbeResult(
                            probe_id="offline-cli-smoke",
                            status=status,
                            source_sha=SHA,
                        ),
                    ],
                )
                self.assertEqual(
                    report.disposition,
                    RuntimeVerificationDisposition.FAILED,
                )

    def test_unknown_duplicate_and_stale_results_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeVerificationError, "unexpected"):
            evaluate_runtime_verification(
                contract(),
                [
                    RuntimeProbeResult(
                        probe_id="unknown-smoke",
                        status=RuntimeProbeStatus.PASS,
                        source_sha=SHA,
                    )
                ],
            )

        duplicate = RuntimeProbeResult(
            probe_id="production-import-smoke",
            status=RuntimeProbeStatus.PASS,
            source_sha=SHA,
        )
        with self.assertRaisesRegex(RuntimeVerificationError, "duplicate"):
            evaluate_runtime_verification(contract(), [duplicate, duplicate])

        with self.assertRaisesRegex(RuntimeVerificationError, "SHA mismatch"):
            evaluate_runtime_verification(
                contract(),
                [
                    RuntimeProbeResult(
                        probe_id="production-import-smoke",
                        status=RuntimeProbeStatus.PASS,
                        source_sha="b" * 40,
                    )
                ],
            )

    def test_attempt_budget_is_enforced(self) -> None:
        with self.assertRaisesRegex(RuntimeVerificationError, "attempt budget"):
            evaluate_runtime_verification(
                contract(),
                [
                    RuntimeProbeResult(
                        probe_id="production-import-smoke",
                        status=RuntimeProbeStatus.PASS,
                        source_sha=SHA,
                        attempt=3,
                    )
                ],
            )

    def test_contract_contains_no_executable_payload_surface(self) -> None:
        payload = contract().canonical_dict()
        self.assertNotIn("command", payload)
        self.assertNotIn("url", payload)
        self.assertNotIn("headers", payload)
        self.assertEqual(
            set(payload),
            {
                "schema_version",
                "verification_id",
                "target_repository",
                "source_sha",
                "environment",
                "required_probe_ids",
                "max_attempts",
                "timeout_seconds",
            },
        )


if __name__ == "__main__":
    unittest.main()
