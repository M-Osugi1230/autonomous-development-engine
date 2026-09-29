from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ade.runtime_probe_executor import execute_runtime_verification_bounded
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
)
from ade.runtime_verification_trigger import (
    RuntimeVerificationReceipt,
    record_runtime_verification_dispatch,
    record_runtime_verification_report,
    runtime_verification_paths,
    runtime_verification_report_path,
)
from github_client import GitHubClient, GitHubError
from runtime_probes import build_runtime_probe_registry

RESULT_PATH = Path(".autodev/runtime/runtime-verification-dispatch-result.json")


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _event_payload() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise ValueError("GITHUB_EVENT_PATH is required")
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow event must be a JSON object")
    client_payload = payload.get("client_payload")
    if not isinstance(client_payload, dict):
        raise ValueError("repository_dispatch client_payload is required")
    return client_payload


def validate_dispatch_payload(
    *,
    event_payload: dict[str, Any],
    contract: RuntimeVerificationContract,
    receipt: RuntimeVerificationReceipt,
) -> None:
    if event_payload.get("task_id") != receipt.task_id:
        raise ValueError("runtime verification dispatch task_id mismatch")
    if event_payload.get("verification_id") != receipt.verification_id:
        raise ValueError("runtime verification dispatch verification_id mismatch")
    if event_payload.get("source_sha") != receipt.source_sha:
        raise ValueError("runtime verification dispatch source_sha mismatch")
    if event_payload.get("target_repository") != receipt.target_repository:
        raise ValueError("runtime verification dispatch repository mismatch")
    if contract.verification_id != receipt.verification_id:
        raise ValueError("runtime verification contract/receipt id mismatch")
    if contract.source_sha != receipt.source_sha:
        raise ValueError("runtime verification contract/receipt source mismatch")
    if contract.target_repository != receipt.target_repository:
        raise ValueError("runtime verification contract/receipt repository mismatch")
    if contract.fingerprint() != receipt.contract_fingerprint:
        raise ValueError("runtime verification contract fingerprint mismatch")


def main() -> int:
    try:
        event = _event_payload()
        task_id = event.get("task_id")
        contract_path, receipt_path = runtime_verification_paths(task_id)

        gh = GitHubClient()
        contract_payload, _ = gh.get_json_file(contract_path)
        receipt_payload, _ = gh.get_json_file(receipt_path)
        contract = RuntimeVerificationContract.from_dict(contract_payload)
        receipt = RuntimeVerificationReceipt.from_dict(receipt_payload)
        validate_dispatch_payload(
            event_payload=event,
            contract=contract,
            receipt=receipt,
        )

        registry = build_runtime_probe_registry()
        dispatch_transition = record_runtime_verification_dispatch(
            contract=contract,
            registry=registry,
            receipt=receipt,
        )
        active_receipt = dispatch_transition.receipt
        if dispatch_transition.changed:
            gh.upsert_json_file(
                receipt_path,
                active_receipt.canonical_dict(),
                message=f"runtime: dispatched {receipt.verification_id}",
            )

        execution = execute_runtime_verification_bounded(
            contract,
            registry,
        )
        report_path = runtime_verification_report_path(active_receipt.task_id)
        gh.upsert_json_file(
            report_path,
            execution.canonical_dict(),
            message=f"runtime: report {active_receipt.verification_id}",
        )
        completion = record_runtime_verification_report(
            contract=contract,
            receipt=active_receipt,
            report=execution.report,
        )
        if completion.changed:
            gh.upsert_json_file(
                receipt_path,
                completion.receipt.canonical_dict(),
                message=f"runtime: {completion.receipt.status.lower()} {completion.receipt.verification_id}",
            )

        result = {
            "schema_version": 1,
            "state": completion.receipt.status,
            "receipt_changed": dispatch_transition.changed or completion.changed,
            "task_id": completion.receipt.task_id,
            "verification_id": completion.receipt.verification_id,
            "target_repository": completion.receipt.target_repository,
            "source_sha": completion.receipt.source_sha,
            "dispatch_count": completion.receipt.dispatch_count,
            "probe_execution_enabled": True,
            "report_fingerprint": execution.report.fingerprint(),
            "attempts_by_probe": [
                {"probe_id": probe_id, "attempts": attempts}
                for probe_id, attempts in execution.attempts_by_probe
            ],
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        if execution.report.disposition is RuntimeVerificationDisposition.FAILED:
            return 2
        return 0
    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "error": str(exc).splitlines()[0][:256],
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
