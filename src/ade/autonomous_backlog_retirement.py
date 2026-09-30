from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from .autonomous_backlog import (
    AutonomousBacklog,
    AutonomousBacklogError,
    BacklogCandidate,
)
from .autonomous_backlog_goal import BacklogGoalHandoff


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _object(payload: object, *, field: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AutonomousBacklogError(f"{field} must be a JSON object")
    return payload


def _sha40(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} must be lowercase SHA40")
    return value


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AutonomousBacklogError(f"{field} must be sha256")
    return value


def _trusted_evidence_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith(".autodev/")
        or value.startswith("/")
        or "\\" in value
        or ".." in value.split("/")
    ):
        raise AutonomousBacklogError("retirement evidence path is unsafe")
    return value


@dataclass(frozen=True, slots=True)
class BacklogRetirement:
    candidate_id: str
    candidate_fingerprint: str
    handoff_fingerprint: str
    planning_request_fingerprint: str
    repository: str
    base_source_sha: str
    verified_merge_sha: str
    evidence_path: str
    evidence_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported backlog retirement version")
        _sha256(self.candidate_fingerprint, field="candidate_fingerprint")
        _sha256(self.handoff_fingerprint, field="handoff_fingerprint")
        _sha256(
            self.planning_request_fingerprint,
            field="planning_request_fingerprint",
        )
        _sha40(self.base_source_sha, field="base_source_sha")
        _sha40(self.verified_merge_sha, field="verified_merge_sha")
        _sha256(self.evidence_fingerprint, field="evidence_fingerprint")
        object.__setattr__(
            self,
            "evidence_path",
            _trusted_evidence_path(self.evidence_path),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "candidate_id": self.candidate_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "handoff_fingerprint": self.handoff_fingerprint,
            "planning_request_fingerprint": self.planning_request_fingerprint,
            "repository": self.repository,
            "base_source_sha": self.base_source_sha,
            "verified_merge_sha": self.verified_merge_sha,
            "evidence_path": self.evidence_path,
            "evidence_fingerprint": self.evidence_fingerprint,
            "state": "RETIRED_VERIFIED",
            "execution_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class BacklogRetirementLedger:
    retirements: tuple[BacklogRetirement, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise AutonomousBacklogError("unsupported retirement ledger version")
        by_id: dict[str, BacklogRetirement] = {}
        for retirement in self.retirements:
            if not isinstance(retirement, BacklogRetirement):
                raise AutonomousBacklogError("retirement ledger contains invalid entry")
            existing = by_id.get(retirement.candidate_id)
            if existing is not None:
                if existing.canonical_dict() != retirement.canonical_dict():
                    raise AutonomousBacklogError(
                        "candidate cannot have conflicting retirements"
                    )
                raise AutonomousBacklogError(
                    f"duplicate retirement candidate id: {retirement.candidate_id}"
                )
            by_id[retirement.candidate_id] = retirement
        object.__setattr__(
            self,
            "retirements",
            tuple(sorted(by_id.values(), key=lambda item: item.candidate_id)),
        )

    @property
    def retired_candidate_ids(self) -> tuple[str, ...]:
        return tuple(item.candidate_id for item in self.retirements)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "retirement_count": len(self.retirements),
            "retirements": [item.canonical_dict() for item in self.retirements],
            "execution_authority": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    def append(self, retirement: BacklogRetirement) -> "BacklogRetirementLedger":
        return BacklogRetirementLedger(retirements=(*self.retirements, retirement))


def retire_from_verified_campaign(
    candidate: BacklogCandidate,
    handoff: BacklogGoalHandoff,
    *,
    evidence_path: str,
    evidence_payload: object,
) -> BacklogRetirement:
    if not isinstance(candidate, BacklogCandidate):
        raise AutonomousBacklogError("candidate must be BacklogCandidate")
    if not isinstance(handoff, BacklogGoalHandoff):
        raise AutonomousBacklogError("handoff must be BacklogGoalHandoff")
    if handoff.candidate_id != candidate.candidate_id:
        raise AutonomousBacklogError("handoff candidate identity mismatch")
    if handoff.candidate_fingerprint != candidate.fingerprint():
        raise AutonomousBacklogError("handoff candidate fingerprint mismatch")

    evidence = _object(evidence_payload, field="campaign evidence")
    if evidence.get("schema_version") != 1:
        raise AutonomousBacklogError("campaign evidence schema_version must be 1")
    if evidence.get("target_repository") != candidate.repository:
        raise AutonomousBacklogError("campaign evidence repository mismatch")
    if evidence.get("terminal_status") != "COMPLETED":
        raise AutonomousBacklogError("campaign evidence is not COMPLETED")
    if evidence.get("failed_tasks") != 0:
        raise AutonomousBacklogError("campaign evidence contains failed tasks")
    if evidence.get("manual_campaign_progress_after_goal_submission") is not False:
        raise AutonomousBacklogError("manual campaign progression is not eligible")

    backlog = _object(evidence.get("autonomous_backlog"), field="backlog evidence")
    if backlog.get("candidate_id") != candidate.candidate_id:
        raise AutonomousBacklogError("campaign does not bind selected backlog candidate")
    if backlog.get("candidate_fingerprint") != candidate.fingerprint():
        raise AutonomousBacklogError("campaign candidate fingerprint mismatch")
    if backlog.get("handoff_fingerprint") != handoff.fingerprint():
        raise AutonomousBacklogError("campaign handoff fingerprint mismatch")
    if (
        backlog.get("planning_request_fingerprint")
        != handoff.request.fingerprint()
    ):
        raise AutonomousBacklogError("campaign PlanningGoal fingerprint mismatch")

    task = _object(evidence.get("task"), field="campaign task")
    base_sha = _sha40(task.get("base_sha"), field="task base_sha")
    merge_sha = _sha40(task.get("merge_commit"), field="task merge_commit")
    if base_sha != candidate.source_sha:
        raise AutonomousBacklogError("campaign base SHA does not match candidate source SHA")

    runtime = _object(
        evidence.get("runtime_verification"),
        field="runtime verification",
    )
    receipt = _object(runtime.get("receipt"), field="runtime receipt")
    report = _object(runtime.get("report"), field="runtime report")
    if receipt.get("status") != "VERIFIED":
        raise AutonomousBacklogError("runtime receipt is not VERIFIED")
    if report.get("disposition") != "VERIFIED":
        raise AutonomousBacklogError("runtime report is not VERIFIED")
    if runtime.get("recovery_triggered") is not False:
        raise AutonomousBacklogError("verified retirement cannot use recovery")
    if runtime.get("human_wait_triggered") is not False:
        raise AutonomousBacklogError("verified retirement cannot use HUMAN_WAIT")
    for source in (
        receipt.get("source_sha"),
        report.get("source_sha"),
        runtime.get("workspace_source_sha"),
    ):
        if source != merge_sha:
            raise AutonomousBacklogError("runtime evidence is not bound to merge SHA")
    if receipt.get("target_repository") != candidate.repository:
        raise AutonomousBacklogError("runtime receipt repository mismatch")

    terminal = _object(evidence.get("terminal_snapshot"), field="terminal snapshot")
    campaign = _object(terminal.get("campaign"), field="terminal campaign")
    state = _object(terminal.get("state"), field="terminal state")
    if campaign.get("status") != "COMPLETED":
        raise AutonomousBacklogError("terminal campaign is not COMPLETED")
    if campaign.get("completed_task_ids") != campaign.get("task_ids"):
        raise AutonomousBacklogError("terminal campaign has incomplete tasks")
    if state.get("status") != "READY":
        raise AutonomousBacklogError("terminal project state is not READY")
    if state.get("current_task_id") is not None:
        raise AutonomousBacklogError("terminal project still has current task")
    if state.get("failed_task_ids") != []:
        raise AutonomousBacklogError("terminal project has failed tasks")

    evidence_path = _trusted_evidence_path(evidence_path)
    evidence_fp = _fingerprint(evidence)
    return BacklogRetirement(
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=candidate.fingerprint(),
        handoff_fingerprint=handoff.fingerprint(),
        planning_request_fingerprint=handoff.request.fingerprint(),
        repository=candidate.repository,
        base_source_sha=candidate.source_sha,
        verified_merge_sha=merge_sha,
        evidence_path=evidence_path,
        evidence_fingerprint=evidence_fp,
    )
