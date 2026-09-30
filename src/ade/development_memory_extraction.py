from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .decisions import DecisionRecord, DecisionStatus
from .development_memory import (
    DevelopmentMemoryError,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from .recovery import RecoveryAction, RecoveryFailure


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CHOICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def trusted_evidence_fingerprint(payload: object) -> str:
    if not isinstance(payload, dict):
        raise DevelopmentMemoryError("trusted evidence must be a JSON object")
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _memory_id(namespace: str, fingerprint: str) -> str:
    if not isinstance(namespace, str) or not namespace:
        raise DevelopmentMemoryError("memory namespace must be non-empty")
    if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
        raise DevelopmentMemoryError("memory source fingerprint must be sha256")
    normalized = re.sub(r"[^a-z0-9._-]+", "-", namespace.casefold()).strip("-")
    if not normalized:
        raise DevelopmentMemoryError("memory namespace is invalid")
    return f"mem-{normalized}-{fingerprint[:20]}"[:96]


def _sha40(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise DevelopmentMemoryError(f"{field} must be a lowercase 40-char SHA")
    return value


def _dict(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DevelopmentMemoryError(f"{field} must be a JSON object")
    return value


def _list(value: object, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DevelopmentMemoryError(f"{field} must be a JSON array")
    return value


def extract_verified_campaign_memory(
    evidence: dict[str, Any],
    *,
    evidence_path: str,
) -> DevelopmentMemoryRecord:
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise DevelopmentMemoryError("campaign evidence schema is unsupported")
    repository = evidence.get("target_repository")
    if not isinstance(repository, str):
        raise DevelopmentMemoryError("campaign evidence target_repository is missing")
    if evidence.get("execution_provenance_clean") is not True:
        raise DevelopmentMemoryError(
            "campaign evidence must have clean execution provenance"
        )

    task = _dict(evidence.get("task"), field="campaign task")
    source_sha = _sha40(task.get("merge_commit"), field="task.merge_commit")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise DevelopmentMemoryError("campaign task_id is missing")

    terminal = _dict(
        evidence.get("terminal_snapshot"),
        field="terminal_snapshot",
    )
    campaign = _dict(terminal.get("campaign"), field="terminal campaign")
    state = _dict(terminal.get("state"), field="terminal state")
    task_ids = _list(campaign.get("task_ids"), field="campaign.task_ids")
    completed = _list(
        campaign.get("completed_task_ids"),
        field="campaign.completed_task_ids",
    )
    failed = _list(state.get("failed_task_ids"), field="state.failed_task_ids")
    if (
        evidence.get("terminal_status") not in {None, "COMPLETED"}
        or campaign.get("status") != "COMPLETED"
        or completed != task_ids
        or state.get("status") != "READY"
        or state.get("current_task_id") is not None
        or failed
        or evidence.get("failed_tasks", 0) != 0
    ):
        raise DevelopmentMemoryError(
            "campaign evidence is not a clean terminal success"
        )

    source_fingerprint = trusted_evidence_fingerprint(evidence)
    return DevelopmentMemoryRecord(
        memory_id=_memory_id("campaign-verified", source_fingerprint),
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=repository,
        source_sha=source_sha,
        statement=(
            "Trusted campaign completed with all planned tasks complete, "
            "no failed tasks, and project state READY."
        ),
        campaign_id=campaign.get("campaign_id"),
        task_id=task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(source_fingerprint,),
        tags=("campaign", "terminal", "verified"),
    )


def extract_runtime_verification_memory(
    evidence: dict[str, Any],
    *,
    evidence_path: str,
) -> DevelopmentMemoryRecord:
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        raise DevelopmentMemoryError("runtime campaign evidence schema is unsupported")
    repository = evidence.get("target_repository")
    if not isinstance(repository, str):
        raise DevelopmentMemoryError("runtime target_repository is missing")
    if evidence.get("execution_provenance_clean") is not True:
        raise DevelopmentMemoryError(
            "runtime evidence must have clean execution provenance"
        )

    task = _dict(evidence.get("task"), field="runtime task")
    source_sha = _sha40(task.get("merge_commit"), field="task.merge_commit")
    task_id = task.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise DevelopmentMemoryError("runtime task_id is missing")

    runtime = _dict(
        evidence.get("runtime_verification"),
        field="runtime_verification",
    )
    contract = _dict(runtime.get("contract"), field="runtime contract")
    receipt = _dict(runtime.get("receipt"), field="runtime receipt")
    report = _dict(runtime.get("report"), field="runtime report")
    results = _list(report.get("results"), field="runtime report results")
    target = _dict(runtime.get("target"), field="runtime target")
    target_evidence = _dict(target.get("evidence"), field="runtime target evidence")

    required = set(contract.get("required_probe_ids", []))
    observed = {
        result.get("probe_id")
        for result in results
        if isinstance(result, dict)
    }
    if (
        not required
        or observed != required
        or receipt.get("status") != "VERIFIED"
        or report.get("disposition") != "VERIFIED"
        or report.get("missing_probe_ids") != []
        or runtime.get("workspace_source_sha") != source_sha
        or contract.get("source_sha") != source_sha
        or receipt.get("source_sha") != source_sha
        or report.get("source_sha") != source_sha
        or target_evidence.get("source_sha") != source_sha
        or receipt.get("target_repository") != repository
        or target_evidence.get("target_repository") != repository
        or any(
            not isinstance(result, dict)
            or result.get("status") != "PASS"
            or result.get("source_sha") != source_sha
            for result in results
        )
        or runtime.get("recovery_triggered") is not False
        or runtime.get("human_wait_triggered") is not False
    ):
        raise DevelopmentMemoryError(
            "runtime verification evidence is not a clean VERIFIED result"
        )

    source_fingerprint = trusted_evidence_fingerprint(evidence)
    report_fingerprint = runtime.get("report_fingerprint")
    fingerprints = [source_fingerprint]
    if isinstance(report_fingerprint, str) and _SHA256.fullmatch(report_fingerprint):
        fingerprints.append(report_fingerprint)

    return DevelopmentMemoryRecord(
        memory_id=_memory_id("runtime-verified", source_fingerprint),
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=repository,
        source_sha=source_sha,
        statement=(
            "Runtime verification passed every required trusted probe "
            "against the exact trusted merge SHA."
        ),
        campaign_id=evidence.get("campaign_id"),
        task_id=task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=tuple(fingerprints),
        tags=("runtime", "source-bound", "verified"),
    )


def extract_recovery_memory(
    recovery: dict[str, Any],
    *,
    evidence_path: str,
    repository: str,
    source_sha: str,
) -> DevelopmentMemoryRecord:
    if not isinstance(recovery, dict) or recovery.get("schema_version") != 1:
        raise DevelopmentMemoryError("recovery evidence schema is unsupported")
    try:
        failure = RecoveryFailure(recovery.get("failure"))
        action = RecoveryAction(recovery.get("action"))
    except (TypeError, ValueError) as exc:
        raise DevelopmentMemoryError("recovery failure/action is invalid") from exc

    task_id = recovery.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise DevelopmentMemoryError("recovery task_id is missing")
    _sha40(source_sha, field="source_sha")

    recovery_fingerprint = recovery.get("fingerprint")
    if (
        not isinstance(recovery_fingerprint, str)
        or _SHA256.fullmatch(recovery_fingerprint) is None
    ):
        raise DevelopmentMemoryError("recovery fingerprint must be sha256")

    progress = _dict(recovery.get("progress"), field="recovery progress")
    expected_progress = {
        "retries",
        "repairs",
        "rebases",
        "replans",
        "repeated_failures",
    }
    if set(progress) != expected_progress or any(
        type(progress[name]) is not int or progress[name] < 0
        for name in expected_progress
    ):
        raise DevelopmentMemoryError("recovery progress is malformed")

    source_fingerprint = trusted_evidence_fingerprint(recovery)
    return DevelopmentMemoryRecord(
        memory_id=_memory_id("recovery", source_fingerprint),
        kind=MemoryKind.REMEDIATION,
        repository=repository,
        source_sha=source_sha,
        statement=(
            f"Trusted recovery classified {failure.value} and selected "
            f"{action.value} under bounded recovery policy."
        ),
        task_id=task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(
            source_fingerprint,
            recovery_fingerprint,
        ),
        tags=("recovery", failure.value.casefold(), action.value.casefold()),
    )


def extract_resolved_decision_memory(
    decision_payload: dict[str, Any],
    *,
    evidence_path: str,
    repository: str,
    source_sha: str,
) -> DevelopmentMemoryRecord:
    if not isinstance(decision_payload, dict):
        raise DevelopmentMemoryError("decision evidence must be a JSON object")
    try:
        decision = DecisionRecord.from_dict(decision_payload)
    except ValueError as exc:
        raise DevelopmentMemoryError("decision evidence is invalid") from exc
    if decision.status is not DecisionStatus.RESOLVED or decision.response is None:
        raise DevelopmentMemoryError("only resolved decisions can become memory")
    _sha40(source_sha, field="source_sha")

    choice = decision.response.selected_option
    if choice is not None and _SAFE_CHOICE.fullmatch(choice):
        statement = (
            f"Trusted human decision selected {choice} for the recorded "
            "blocking task."
        )
        choice_tag = "choice-" + choice.casefold()
        tags = ("decision", "human", "resolved", choice_tag)
    else:
        statement = "Trusted human decision resolved the recorded blocking task."
        tags = ("decision", "human", "resolved")

    source_fingerprint = trusted_evidence_fingerprint(decision.to_dict())
    return DevelopmentMemoryRecord(
        memory_id=_memory_id("decision", source_fingerprint),
        kind=MemoryKind.DECISION,
        repository=repository,
        source_sha=source_sha,
        statement=statement,
        task_id=decision.request.blocking_task_id,
        evidence_paths=(evidence_path,),
        evidence_fingerprints=(source_fingerprint,),
        tags=tags,
    )
