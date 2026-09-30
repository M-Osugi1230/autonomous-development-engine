from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any

from .autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
)
from .development_memory_feedback import runtime_report_from_wrapper
from .remote_execution import RemoteExecutionReceipt
from .runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
    evaluate_runtime_verification,
)
from .runtime_verification_trigger import RuntimeVerificationReceipt


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} is invalid")
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} must be lowercase SHA40")
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} must be sha256")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise AutonomousBacklogError("retirement repository must be owner/name")
    return value


def _evidence_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 240:
        raise AutonomousBacklogError("retirement evidence path is invalid")
    if value.startswith("/") or "\\" in value:
        raise AutonomousBacklogError("retirement evidence path is unsafe")
    path = PurePosixPath(value)
    if "." in path.parts or ".." in path.parts or str(path) != value:
        raise AutonomousBacklogError("retirement evidence path must be normalized")
    if not value.startswith(".autodev/"):
        raise AutonomousBacklogError(
            "retirement evidence must remain inside .autodev/"
        )
    return value


@dataclass(frozen=True, slots=True)
class BacklogRetirementRecord:
    retirement_id: str
    candidate_id: str
    candidate_fingerprint: str
    goal_handoff_fingerprint: str
    request_id: str
    campaign_id: str
    repository: str
    original_source_sha: str
    verified_source_sha: str
    final_task_id: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported retirement schema version")
        object.__setattr__(
            self,
            "retirement_id",
            _identifier(self.retirement_id, field="retirement_id"),
        )
        object.__setattr__(
            self,
            "candidate_id",
            _identifier(self.candidate_id, field="candidate_id"),
        )
        object.__setattr__(
            self,
            "request_id",
            _identifier(self.request_id, field="request_id"),
        )
        object.__setattr__(
            self,
            "campaign_id",
            _identifier(self.campaign_id, field="campaign_id"),
        )
        object.__setattr__(
            self,
            "final_task_id",
            _identifier(self.final_task_id, field="final_task_id"),
        )
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _sha256(self.candidate_fingerprint, field="candidate_fingerprint"),
        )
        object.__setattr__(
            self,
            "goal_handoff_fingerprint",
            _sha256(
                self.goal_handoff_fingerprint,
                field="goal_handoff_fingerprint",
            ),
        )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "original_source_sha",
            _sha40(self.original_source_sha, field="original_source_sha"),
        )
        object.__setattr__(
            self,
            "verified_source_sha",
            _sha40(self.verified_source_sha, field="verified_source_sha"),
        )
        paths = tuple(_evidence_path(path) for path in self.evidence_paths)
        fingerprints = tuple(
            _sha256(value, field="evidence_fingerprint")
            for value in self.evidence_fingerprints
        )
        if not paths or len(paths) != len(fingerprints):
            raise AutonomousBacklogError(
                "retirement evidence paths/fingerprints must be non-empty and aligned"
            )
        if len(paths) > 10 or len(set(paths)) != len(paths):
            raise AutonomousBacklogError(
                "retirement evidence exceeds budget or contains duplicates"
            )
        object.__setattr__(self, "evidence_paths", paths)
        object.__setattr__(self, "evidence_fingerprints", fingerprints)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "retirement_id": self.retirement_id,
            "candidate_id": self.candidate_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "goal_handoff_fingerprint": self.goal_handoff_fingerprint,
            "request_id": self.request_id,
            "campaign_id": self.campaign_id,
            "repository": self.repository,
            "original_source_sha": self.original_source_sha,
            "verified_source_sha": self.verified_source_sha,
            "final_task_id": self.final_task_id,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(self.evidence_fingerprints),
            "retirement_authority": "trusted-verified-completion-v1",
            "execution_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: object) -> "BacklogRetirementRecord":
        if not isinstance(payload, dict):
            raise AutonomousBacklogError("retirement must be a JSON object")
        allowed = {
            "schema_version",
            "retirement_id",
            "candidate_id",
            "candidate_fingerprint",
            "goal_handoff_fingerprint",
            "request_id",
            "campaign_id",
            "repository",
            "original_source_sha",
            "verified_source_sha",
            "final_task_id",
            "evidence_paths",
            "evidence_fingerprints",
            "retirement_authority",
            "execution_authority",
            "auto_dispatch",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise AutonomousBacklogError(
                f"unknown retirement fields: {sorted(unknown)}"
            )
        if payload.get("retirement_authority") != "trusted-verified-completion-v1":
            raise AutonomousBacklogError("retirement authority is invalid")
        if payload.get("execution_authority", False) is not False:
            raise AutonomousBacklogError(
                "retirement cannot grant execution authority"
            )
        if payload.get("auto_dispatch", False) is not False:
            raise AutonomousBacklogError("retirement cannot auto-dispatch")
        paths = payload.get("evidence_paths")
        fingerprints = payload.get("evidence_fingerprints")
        if not isinstance(paths, list) or not isinstance(fingerprints, list):
            raise AutonomousBacklogError("retirement evidence must be lists")
        return cls(
            schema_version=payload.get("schema_version", 0),
            retirement_id=payload.get("retirement_id", ""),
            candidate_id=payload.get("candidate_id", ""),
            candidate_fingerprint=payload.get("candidate_fingerprint", ""),
            goal_handoff_fingerprint=payload.get(
                "goal_handoff_fingerprint",
                "",
            ),
            request_id=payload.get("request_id", ""),
            campaign_id=payload.get("campaign_id", ""),
            repository=payload.get("repository", ""),
            original_source_sha=payload.get("original_source_sha", ""),
            verified_source_sha=payload.get("verified_source_sha", ""),
            final_task_id=payload.get("final_task_id", ""),
            evidence_paths=tuple(paths),
            evidence_fingerprints=tuple(fingerprints),
        )


def build_verified_backlog_retirement(
    *,
    backlog: AutonomousBacklog,
    handoff: object,
    campaign_payload: object,
    state_payload: object,
    remote_execution_payload: object,
    runtime_contract_payload: object,
    runtime_receipt_payload: object,
    runtime_report_wrapper_payload: object,
    handoff_path: str,
    campaign_path: str,
    state_path: str,
    remote_execution_path: str,
    runtime_contract_path: str,
    runtime_receipt_path: str,
    runtime_report_path: str,
) -> BacklogRetirementRecord:
    # Local import avoids a module cycle because autonomous_backlog_goal depends
    # on backlog resolution, while resolution consumes retirement records.
    from .autonomous_backlog_goal import BacklogGoalHandoff

    if not isinstance(backlog, AutonomousBacklog):
        raise AutonomousBacklogError("backlog must be AutonomousBacklog")
    if not isinstance(handoff, BacklogGoalHandoff):
        raise AutonomousBacklogError("handoff must be BacklogGoalHandoff")

    candidates = {
        candidate.candidate_id: candidate for candidate in backlog.candidates
    }
    candidate = candidates.get(handoff.candidate_id)
    if candidate is None:
        raise AutonomousBacklogError("retirement candidate is absent from backlog")
    if candidate.fingerprint() != handoff.candidate_fingerprint:
        raise AutonomousBacklogError("retirement candidate fingerprint drift")
    if handoff.request.target_repository != candidate.repository:
        raise AutonomousBacklogError("retirement handoff repository mismatch")

    if not isinstance(campaign_payload, dict):
        raise AutonomousBacklogError("campaign evidence must be an object")
    if campaign_payload.get("campaign_id") != handoff.request.campaign_id:
        raise AutonomousBacklogError("retirement campaign does not bind handoff")
    if campaign_payload.get("status") != "COMPLETED":
        raise AutonomousBacklogError("retirement requires COMPLETED campaign")
    task_ids = campaign_payload.get("task_ids")
    completed_task_ids = campaign_payload.get("completed_task_ids")
    if (
        not isinstance(task_ids, list)
        or not task_ids
        or not isinstance(completed_task_ids, list)
        or set(completed_task_ids) != set(task_ids)
        or len(completed_task_ids) != len(task_ids)
    ):
        raise AutonomousBacklogError(
            "retirement requires every campaign task to be complete"
        )

    if not isinstance(state_payload, dict):
        raise AutonomousBacklogError("project state evidence must be an object")
    if (
        state_payload.get("status") != "READY"
        or state_payload.get("current_task_id") is not None
        or state_payload.get("failed_task_ids") != []
    ):
        raise AutonomousBacklogError(
            "retirement requires clean terminal ProjectState"
        )
    completed_state = state_payload.get("completed_task_ids")
    if (
        not isinstance(completed_state, list)
        or not set(task_ids).issubset(set(completed_state))
    ):
        raise AutonomousBacklogError(
            "ProjectState does not prove campaign task completion"
        )

    try:
        remote = RemoteExecutionReceipt.from_dict(remote_execution_payload)
        contract = RuntimeVerificationContract.from_dict(
            runtime_contract_payload
        )
        receipt = RuntimeVerificationReceipt.from_dict(runtime_receipt_payload)
        report = runtime_report_from_wrapper(runtime_report_wrapper_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise AutonomousBacklogError(
            "retirement execution/runtime evidence is invalid"
        ) from exc

    if remote.status != "MERGED":
        raise AutonomousBacklogError("retirement requires trusted merged execution")
    if remote.target_repository != candidate.repository:
        raise AutonomousBacklogError("retirement execution repository mismatch")
    if remote.task_id not in task_ids:
        raise AutonomousBacklogError("retirement final task is outside campaign")
    if receipt.task_id != remote.task_id:
        raise AutonomousBacklogError("retirement runtime task mismatch")
    if receipt.status != "VERIFIED":
        raise AutonomousBacklogError("retirement requires VERIFIED runtime receipt")
    if receipt.dispatch_count != 1:
        raise AutonomousBacklogError(
            "retirement requires a single trusted runtime dispatch"
        )
    if (
        contract.verification_id != receipt.verification_id
        or contract.target_repository != candidate.repository
        or contract.source_sha != receipt.source_sha
        or contract.fingerprint() != receipt.contract_fingerprint
    ):
        raise AutonomousBacklogError("retirement runtime binding mismatch")

    evaluated = evaluate_runtime_verification(contract, report.results)
    if evaluated.canonical_dict() != report.canonical_dict():
        raise AutonomousBacklogError(
            "retirement runtime report differs from trusted evaluation"
        )
    if report.disposition is not RuntimeVerificationDisposition.VERIFIED:
        raise AutonomousBacklogError("retirement runtime report is not VERIFIED")

    evidence_payloads = (
        handoff.canonical_dict(),
        campaign_payload,
        state_payload,
        remote.to_dict(),
        contract.canonical_dict(),
        receipt.canonical_dict(),
        runtime_report_wrapper_payload,
    )
    evidence_paths = (
        handoff_path,
        campaign_path,
        state_path,
        remote_execution_path,
        runtime_contract_path,
        runtime_receipt_path,
        runtime_report_path,
    )
    normalized_paths = tuple(_evidence_path(path) for path in evidence_paths)
    fingerprints = tuple(_fingerprint(payload) for payload in evidence_payloads)

    identity = _fingerprint(
        {
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.fingerprint(),
            "goal_handoff_fingerprint": handoff.fingerprint(),
            "campaign_id": handoff.request.campaign_id,
            "final_task_id": receipt.task_id,
            "verified_source_sha": contract.source_sha,
            "runtime_report_fingerprint": report.fingerprint(),
        }
    )
    return BacklogRetirementRecord(
        retirement_id="retire-" + identity[:24],
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=candidate.fingerprint(),
        goal_handoff_fingerprint=handoff.fingerprint(),
        request_id=handoff.request.request_id,
        campaign_id=handoff.request.campaign_id,
        repository=candidate.repository,
        original_source_sha=candidate.source_sha,
        verified_source_sha=contract.source_sha,
        final_task_id=receipt.task_id,
        evidence_paths=normalized_paths,
        evidence_fingerprints=fingerprints,
    )
