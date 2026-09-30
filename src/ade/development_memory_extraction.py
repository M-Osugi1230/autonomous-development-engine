from __future__ import annotations

import hashlib
import json
from typing import Any

from .decisions import DecisionRecord, DecisionStatus
from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from .recovery import RecoveryAction
from .recovery_runtime import RecoveryRecord


def evidence_fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _object(payload: object, *, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DevelopmentMemoryError(f"{field} must be a JSON object")
    return payload


def _list(payload: object, *, field: str) -> list[Any]:
    if not isinstance(payload, list):
        raise DevelopmentMemoryError(f"{field} must be a JSON array")
    return payload


def _memory_id(*, category: str, evidence_sha256: str, identity: str) -> str:
    raw = f"{category}:{evidence_sha256}:{identity}".encode("utf-8")
    return "mem-" + hashlib.sha256(raw).hexdigest()[:24]


def extract_completed_campaign_memory(
    *,
    evidence_path: str,
    evidence_payload: object,
) -> DevelopmentMemoryRecord:
    evidence = _object(evidence_payload, field="campaign evidence")
    if evidence.get("schema_version") != 1:
        raise DevelopmentMemoryError("campaign evidence schema_version must be 1")

    repository = evidence.get("target_repository")
    campaign_id = evidence.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise DevelopmentMemoryError("campaign evidence requires campaign_id")
    if evidence.get("terminal_status") != "COMPLETED":
        raise DevelopmentMemoryError("campaign evidence is not terminal COMPLETED")
    if evidence.get("failed_tasks") != 0:
        raise DevelopmentMemoryError("campaign evidence contains failed tasks")

    task = _object(evidence.get("task"), field="campaign task")
    task_id = task.get("task_id")
    merge_sha = task.get("merge_commit")
    if not isinstance(task_id, str) or not task_id:
        raise DevelopmentMemoryError("campaign evidence requires task_id")
    if not isinstance(merge_sha, str):
        raise DevelopmentMemoryError("campaign evidence requires merge_commit")

    terminal = _object(evidence.get("terminal_snapshot"), field="terminal snapshot")
    campaign = _object(terminal.get("campaign"), field="terminal campaign")
    state = _object(terminal.get("state"), field="terminal state")
    if campaign.get("campaign_id") != campaign_id:
        raise DevelopmentMemoryError("terminal campaign identity mismatch")
    if campaign.get("status") != "COMPLETED":
        raise DevelopmentMemoryError("terminal campaign is not COMPLETED")
    if campaign.get("completed_task_ids") != campaign.get("task_ids"):
        raise DevelopmentMemoryError("terminal campaign has incomplete tasks")
    if state.get("status") != "READY":
        raise DevelopmentMemoryError("terminal project state is not READY")
    if state.get("current_task_id") is not None:
        raise DevelopmentMemoryError("terminal project still has a current task")
    if state.get("failed_task_ids") != []:
        raise DevelopmentMemoryError("terminal project contains failed tasks")

    fingerprint = evidence_fingerprint(evidence)
    return DevelopmentMemoryRecord(
        memory_id=_memory_id(
            category="campaign-completed",
            evidence_sha256=fingerprint,
            identity=campaign_id,
        ),
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=repository,
        source_sha=merge_sha,
        statement=(
            "Campaign completed with all declared tasks complete, zero failed tasks, "
            "and terminal project state READY."
        ),
        campaign_id=campaign_id,
        task_id=task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(fingerprint,),
        tags=("campaign", "completed", "verified"),
    )


def extract_verified_runtime_memory(
    *,
    evidence_path: str,
    evidence_payload: object,
) -> DevelopmentMemoryRecord:
    evidence = _object(evidence_payload, field="runtime campaign evidence")
    if evidence.get("schema_version") != 1:
        raise DevelopmentMemoryError("runtime campaign evidence schema_version must be 1")

    repository = evidence.get("target_repository")
    campaign_id = evidence.get("campaign_id")
    task = _object(evidence.get("task"), field="runtime task")
    task_id = task.get("task_id")
    merge_sha = task.get("merge_commit")
    runtime = _object(evidence.get("runtime_verification"), field="runtime verification")
    contract = _object(runtime.get("contract"), field="runtime contract")
    receipt = _object(runtime.get("receipt"), field="runtime receipt")
    report = _object(runtime.get("report"), field="runtime report")
    results = _list(report.get("results"), field="runtime results")

    if not isinstance(campaign_id, str) or not campaign_id:
        raise DevelopmentMemoryError("runtime evidence requires campaign_id")
    if not isinstance(task_id, str) or not task_id:
        raise DevelopmentMemoryError("runtime evidence requires task_id")
    if not isinstance(merge_sha, str):
        raise DevelopmentMemoryError("runtime evidence requires merge_commit")
    if receipt.get("status") != "VERIFIED":
        raise DevelopmentMemoryError("runtime receipt is not VERIFIED")
    if report.get("disposition") != "VERIFIED":
        raise DevelopmentMemoryError("runtime report is not VERIFIED")
    if runtime.get("recovery_triggered") is not False:
        raise DevelopmentMemoryError("runtime verification used recovery")
    if runtime.get("human_wait_triggered") is not False:
        raise DevelopmentMemoryError("runtime verification entered HUMAN_WAIT")

    source_values = {
        merge_sha,
        contract.get("source_sha"),
        receipt.get("source_sha"),
        report.get("source_sha"),
        runtime.get("workspace_source_sha"),
    }
    if source_values != {merge_sha}:
        raise DevelopmentMemoryError("runtime source SHA binding mismatch")
    if contract.get("target_repository") != repository:
        raise DevelopmentMemoryError("runtime contract repository mismatch")
    if receipt.get("target_repository") != repository:
        raise DevelopmentMemoryError("runtime receipt repository mismatch")
    if receipt.get("task_id") != task_id:
        raise DevelopmentMemoryError("runtime receipt task mismatch")

    required = contract.get("required_probe_ids")
    if not isinstance(required, list) or not required:
        raise DevelopmentMemoryError("runtime contract has no required probes")
    required_ids = set(required)
    result_ids: set[str] = set()
    for result in results:
        row = _object(result, field="runtime probe result")
        probe_id = row.get("probe_id")
        if not isinstance(probe_id, str) or not probe_id:
            raise DevelopmentMemoryError("runtime probe result has invalid probe_id")
        if probe_id in result_ids:
            raise DevelopmentMemoryError("runtime report contains duplicate probe")
        result_ids.add(probe_id)
        if row.get("status") != "PASS":
            raise DevelopmentMemoryError("runtime report contains non-PASS probe")
        if row.get("source_sha") != merge_sha:
            raise DevelopmentMemoryError("runtime probe source SHA mismatch")

    if result_ids != required_ids:
        raise DevelopmentMemoryError("runtime probe set does not match contract")

    fingerprint = evidence_fingerprint(evidence)
    return DevelopmentMemoryRecord(
        memory_id=_memory_id(
            category="runtime-verified",
            evidence_sha256=fingerprint,
            identity=task_id,
        ),
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=repository,
        source_sha=merge_sha,
        statement=(
            "Runtime verification passed every required trusted probe against the exact "
            "trusted merge SHA without recovery or HUMAN_WAIT."
        ),
        campaign_id=campaign_id,
        task_id=task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(fingerprint,),
        tags=("runtime", "verified", "source-bound"),
    )


def extract_recovery_memory(
    *,
    evidence_path: str,
    recovery_payload: object,
    repository: str,
    source_sha: str,
) -> DevelopmentMemoryRecord:
    payload = _object(recovery_payload, field="recovery evidence")
    if payload.get("schema_version") != 1:
        raise DevelopmentMemoryError("recovery evidence schema_version must be 1")
    try:
        record = RecoveryRecord.from_dict(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise DevelopmentMemoryError("recovery evidence is invalid") from exc

    fingerprint = evidence_fingerprint(payload)
    kind = (
        MemoryKind.FAILURE
        if record.action in {RecoveryAction.HUMAN_WAIT, RecoveryAction.FAIL}
        else MemoryKind.REMEDIATION
    )
    return DevelopmentMemoryRecord(
        memory_id=_memory_id(
            category="recovery",
            evidence_sha256=fingerprint,
            identity=record.task_id,
        ),
        kind=kind,
        repository=repository,
        source_sha=source_sha,
        statement=(
            f"Trusted recovery classified {record.failure.value} and selected "
            f"{record.action.value} under bounded recovery policy."
        ),
        task_id=record.task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(fingerprint,),
        tags=("recovery", record.failure.value.casefold(), record.action.value.casefold()),
    )


def extract_resolved_decision_memory(
    *,
    evidence_path: str,
    decision_store_payload: object,
    decision_id: str,
    repository: str,
    source_sha: str,
) -> DevelopmentMemoryRecord:
    store = _object(decision_store_payload, field="decision store")
    if store.get("schema_version") != 1:
        raise DevelopmentMemoryError("decision store schema_version must be 1")
    raw_records = _list(store.get("decisions"), field="decision records")

    matches: list[DecisionRecord] = []
    for raw in raw_records:
        try:
            record = DecisionRecord.from_dict(_object(raw, field="decision record"))
        except (TypeError, ValueError) as exc:
            raise DevelopmentMemoryError("decision store contains invalid record") from exc
        if record.decision_id == decision_id:
            matches.append(record)

    if len(matches) != 1:
        raise DevelopmentMemoryError("decision_id must match exactly one decision record")
    record = matches[0]
    if record.status is not DecisionStatus.RESOLVED or record.response is None:
        raise DevelopmentMemoryError("decision is not RESOLVED")
    selected = record.response.selected_option
    if selected is None:
        raise DevelopmentMemoryError(
            "resolved free-text decision is not eligible for automatic memory"
        )
    if selected not in record.request.options:
        raise DevelopmentMemoryError("resolved decision option is not trusted")

    fingerprint = evidence_fingerprint(store)
    return DevelopmentMemoryRecord(
        memory_id=_memory_id(
            category="decision",
            evidence_sha256=fingerprint,
            identity=record.decision_id,
        ),
        kind=MemoryKind.DECISION,
        repository=repository,
        source_sha=source_sha,
        statement=(
            f"Human decision {record.decision_id} resolved with selected option {selected}."
        ),
        task_id=record.request.blocking_task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(fingerprint,),
        tags=("decision", "human-resolved"),
    )


def extract_trusted_memories(
    *,
    campaign_evidence_path: str,
    campaign_evidence_payload: object,
    recovery_evidence_path: str | None = None,
    recovery_payload: object | None = None,
    decision_evidence_path: str | None = None,
    decision_store_payload: object | None = None,
    decision_id: str | None = None,
    recovery_repository: str | None = None,
    recovery_source_sha: str | None = None,
    decision_repository: str | None = None,
    decision_source_sha: str | None = None,
) -> tuple[DevelopmentMemoryRecord, ...]:
    records = [
        extract_completed_campaign_memory(
            evidence_path=campaign_evidence_path,
            evidence_payload=campaign_evidence_payload,
        ),
        extract_verified_runtime_memory(
            evidence_path=campaign_evidence_path,
            evidence_payload=campaign_evidence_payload,
        ),
    ]

    recovery_values = (
        recovery_evidence_path,
        recovery_payload,
        recovery_repository,
        recovery_source_sha,
    )
    if any(value is not None for value in recovery_values):
        if not all(value is not None for value in recovery_values):
            raise DevelopmentMemoryError("recovery extraction inputs must be complete")
        records.append(
            extract_recovery_memory(
                evidence_path=recovery_evidence_path,  # type: ignore[arg-type]
                recovery_payload=recovery_payload,
                repository=recovery_repository,  # type: ignore[arg-type]
                source_sha=recovery_source_sha,  # type: ignore[arg-type]
            )
        )

    decision_values = (
        decision_evidence_path,
        decision_store_payload,
        decision_id,
        decision_repository,
        decision_source_sha,
    )
    if any(value is not None for value in decision_values):
        if not all(value is not None for value in decision_values):
            raise DevelopmentMemoryError("decision extraction inputs must be complete")
        records.append(
            extract_resolved_decision_memory(
                evidence_path=decision_evidence_path,  # type: ignore[arg-type]
                decision_store_payload=decision_store_payload,
                decision_id=decision_id,  # type: ignore[arg-type]
                repository=decision_repository,  # type: ignore[arg-type]
                source_sha=decision_source_sha,  # type: ignore[arg-type]
            )
        )

    return tuple(records)
