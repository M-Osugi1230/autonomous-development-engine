from __future__ import annotations

import os
import time
import unittest

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


def contract(*probe_ids: str, max_attempts: int = 2, timeout_seconds: int = 1):
    return RuntimeVerificationContract(
        verification_id="runtime-executor-test",
        target_repository="example/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=probe_ids,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
    )


def _pass(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    return RuntimeProbeObservation(RuntimeProbeStatus.PASS, detail_code="passed")


def _fail(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    return RuntimeProbeObservation(RuntimeProbeStatus.FAIL, detail_code="failed")


def _timeout(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    time.sleep(5)
    return RuntimeProbeObservation(RuntimeProbeStatus.PASS)


def _error_then_pass(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    if invocation.attempt == 1:
        return RuntimeProbeObservation(
            RuntimeProbeStatus.ERROR,
            detail_code="transient",
        )
    return RuntimeProbeObservation(
        RuntimeProbeStatus.PASS,
        detail_code="recovered",
    )


def _authority_probe(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
    clean = (
        invocation.repository_write_authority is False
        and invocation.credential_authority is False
        and invocation.network_authority is False
        and invocation.deployment_authority is False
        and invocation.timeout_seconds == 1
        and "GITHUB_TOKEN" not in os.environ
        and "OPENAI_API_KEY" not in os.environ
    )
    return RuntimeProbeObservation(
        RuntimeProbeStatus.PASS if clean else RuntimeProbeStatus.FAIL,
        detail_code="authority-clean" if clean else "authority-expanded",
    )


class RuntimeProbeExecutorTests(unittest.TestCase):
    def test_all_pass_returns_verified(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration("probe-a", "probe-a-v1", _pass),
                RuntimeProbeRegistration("probe-b", "probe-b-v1", _pass),
            ]
        )
        execution = execute_runtime_verification_bounded(
            contract("probe-a", "probe-b"),
            registry,
        )
        self.assertEqual(
            execution.report.disposition,
            RuntimeVerificationDisposition.VERIFIED,
        )
        self.assertEqual(
            execution.attempts_by_probe,
            (("probe-a", 1), ("probe-b", 1)),
        )

    def test_error_retries_within_contract_budget_then_passes(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    "probe-a",
                    "probe-a-v1",
                    _error_then_pass,
                )
            ]
        )
        execution = execute_runtime_verification_bounded(
            contract("probe-a", max_attempts=2),
            registry,
        )
        self.assertEqual(
            execution.report.disposition,
            RuntimeVerificationDisposition.VERIFIED,
        )
        self.assertEqual(execution.attempts_by_probe, (("probe-a", 2),))
        self.assertEqual(execution.report.results[0].attempt, 2)

    def test_fail_is_terminal_and_is_not_retried(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "probe-a-v1", _fail)]
        )
        execution = execute_runtime_verification_bounded(
            contract("probe-a", max_attempts=3),
            registry,
        )
        self.assertEqual(
            execution.report.disposition,
            RuntimeVerificationDisposition.FAILED,
        )
        self.assertEqual(execution.attempts_by_probe, (("probe-a", 1),))
        self.assertEqual(execution.report.results[0].attempt, 1)

    def test_timeout_is_hard_bounded_and_secret_free(self) -> None:
        registry = TrustedRuntimeProbeRegistry(
            [RuntimeProbeRegistration("probe-a", "probe-a-v1", _timeout)]
        )
        started = time.monotonic()
        execution = execute_runtime_verification_bounded(
            contract("probe-a", max_attempts=1, timeout_seconds=1),
            registry,
        )
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 4.0)
        self.assertEqual(
            execution.report.disposition,
            RuntimeVerificationDisposition.FAILED,
        )
        result = execution.report.results[0]
        self.assertEqual(result.status, RuntimeProbeStatus.ERROR)
        self.assertEqual(result.detail_code, "probe-timeout")

    def test_child_environment_and_authority_are_minimized(self) -> None:
        old_token = os.environ.get("GITHUB_TOKEN")
        old_key = os.environ.get("OPENAI_API_KEY")
        os.environ["GITHUB_TOKEN"] = "should-not-reach-probe"
        os.environ["OPENAI_API_KEY"] = "should-not-reach-probe"
        try:
            registry = TrustedRuntimeProbeRegistry(
                [
                    RuntimeProbeRegistration(
                        "probe-a",
                        "probe-a-v1",
                        _authority_probe,
                    )
                ]
            )
            execution = execute_runtime_verification_bounded(
                contract("probe-a", timeout_seconds=1),
                registry,
            )
        finally:
            if old_token is None:
                os.environ.pop("GITHUB_TOKEN", None)
            else:
                os.environ["GITHUB_TOKEN"] = old_token
            if old_key is None:
                os.environ.pop("OPENAI_API_KEY", None)
            else:
                os.environ["OPENAI_API_KEY"] = old_key

        self.assertEqual(
            execution.report.disposition,
            RuntimeVerificationDisposition.VERIFIED,
        )
        self.assertEqual(
            execution.report.results[0].detail_code,
            "authority-clean",
        )


if __name__ == "__main__":
    unittest.main()
