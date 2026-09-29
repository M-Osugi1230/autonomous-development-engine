from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
import os
from queue import Empty
from typing import Any

from .runtime_probe_registry import TrustedRuntimeProbeRegistry
from .runtime_verification import (
    RuntimeProbeResult,
    RuntimeProbeStatus,
    RuntimeVerificationContract,
    RuntimeVerificationError,
    RuntimeVerificationReport,
    evaluate_runtime_verification,
)


_SAFE_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONPATH",
    "PYTHONHOME",
)


def _sanitize_probe_environment() -> None:
    preserved = {
        key: os.environ[key]
        for key in _SAFE_ENV_KEYS
        if key in os.environ
    }
    os.environ.clear()
    os.environ.update(preserved)
    os.environ["ADE_RUNTIME_CREDENTIAL_AUTHORITY"] = "none"
    os.environ["ADE_RUNTIME_NETWORK_AUTHORITY"] = "none"
    os.environ["ADE_RUNTIME_DEPLOYMENT_AUTHORITY"] = "none"


def _result_from_dict(payload: dict[str, Any]) -> RuntimeProbeResult:
    return RuntimeProbeResult(
        schema_version=payload.get("schema_version", 0),
        probe_id=str(payload.get("probe_id", "")),
        status=RuntimeProbeStatus(str(payload.get("status", ""))),
        source_sha=str(payload.get("source_sha", "")),
        attempt=payload.get("attempt", 0),
        detail_code=payload.get("detail_code"),
    )


def _probe_worker(
    registry: TrustedRuntimeProbeRegistry,
    contract: RuntimeVerificationContract,
    probe_id: str,
    attempt: int,
    queue,
) -> None:
    _sanitize_probe_environment()
    try:
        result = registry.execute(
            contract,
            probe_id=probe_id,
            attempt=attempt,
        )
        queue.put({"kind": "result", "payload": result.canonical_dict()})
    except BaseException:
        queue.put({"kind": "error"})


def execute_probe_bounded(
    contract: RuntimeVerificationContract,
    registry: TrustedRuntimeProbeRegistry,
    *,
    probe_id: str,
    attempt: int,
) -> RuntimeProbeResult:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError(
            "contract must be a RuntimeVerificationContract"
        )
    if not isinstance(registry, TrustedRuntimeProbeRegistry):
        raise RuntimeVerificationError(
            "registry must be a TrustedRuntimeProbeRegistry"
        )
    registry.ensure_contract_supported(contract)
    if probe_id not in contract.required_probe_ids:
        raise RuntimeVerificationError(
            f"runtime probe is not required by contract: {probe_id}"
        )
    if type(attempt) is not int or not 1 <= attempt <= contract.max_attempts:
        raise RuntimeVerificationError(
            f"runtime probe attempt exceeds trusted budget: {probe_id}"
        )

    try:
        context = multiprocessing.get_context("fork")
    except ValueError as exc:
        raise RuntimeVerificationError(
            "hard-timeout probe execution requires fork support"
        ) from exc

    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_probe_worker,
        args=(registry, contract, probe_id, attempt, queue),
        daemon=True,
    )
    process.start()
    process.join(timeout=contract.timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        return RuntimeProbeResult(
            probe_id=probe_id,
            status=RuntimeProbeStatus.ERROR,
            source_sha=contract.source_sha,
            attempt=attempt,
            detail_code="probe-timeout",
        )

    try:
        message = queue.get(timeout=1)
    except Empty:
        return RuntimeProbeResult(
            probe_id=probe_id,
            status=RuntimeProbeStatus.ERROR,
            source_sha=contract.source_sha,
            attempt=attempt,
            detail_code="probe-process-error",
        )
    finally:
        queue.close()

    if not isinstance(message, dict) or message.get("kind") != "result":
        return RuntimeProbeResult(
            probe_id=probe_id,
            status=RuntimeProbeStatus.ERROR,
            source_sha=contract.source_sha,
            attempt=attempt,
            detail_code="probe-process-error",
        )
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return RuntimeProbeResult(
            probe_id=probe_id,
            status=RuntimeProbeStatus.ERROR,
            source_sha=contract.source_sha,
            attempt=attempt,
            detail_code="probe-process-error",
        )
    result = _result_from_dict(payload)
    if (
        result.probe_id != probe_id
        or result.source_sha != contract.source_sha
        or result.attempt != attempt
    ):
        raise RuntimeVerificationError(
            "bounded runtime probe result identity drift"
        )
    return result


@dataclass(frozen=True, slots=True)
class RuntimeProbeExecution:
    report: RuntimeVerificationReport
    attempts_by_probe: tuple[tuple[str, int], ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "report": self.report.canonical_dict(),
            "report_fingerprint": self.report.fingerprint(),
            "attempts_by_probe": [
                {"probe_id": probe_id, "attempts": attempts}
                for probe_id, attempts in self.attempts_by_probe
            ],
        }


def execute_runtime_verification_bounded(
    contract: RuntimeVerificationContract,
    registry: TrustedRuntimeProbeRegistry,
) -> RuntimeProbeExecution:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError(
            "contract must be a RuntimeVerificationContract"
        )
    if not isinstance(registry, TrustedRuntimeProbeRegistry):
        raise RuntimeVerificationError(
            "registry must be a TrustedRuntimeProbeRegistry"
        )
    registry.ensure_contract_supported(contract)

    final_results: list[RuntimeProbeResult] = []
    attempts: list[tuple[str, int]] = []
    for probe_id in contract.required_probe_ids:
        final: RuntimeProbeResult | None = None
        used = 0
        for attempt in range(1, contract.max_attempts + 1):
            used = attempt
            current = execute_probe_bounded(
                contract,
                registry,
                probe_id=probe_id,
                attempt=attempt,
            )
            final = current
            if current.status is not RuntimeProbeStatus.ERROR:
                break
        assert final is not None
        final_results.append(final)
        attempts.append((probe_id, used))

    report = evaluate_runtime_verification(contract, final_results)
    return RuntimeProbeExecution(
        report=report,
        attempts_by_probe=tuple(attempts),
    )
