from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any

from .autonomous_backlog import AutonomousBacklog
from .autonomous_backlog_feedback import (
    BacklogRetirementRecord,
    build_verified_backlog_retirement,
)
from .autonomous_backlog_goal import BacklogGoalHandoff
from .improvement_bridge import ImprovementBridgeBundle
from .improvement_goal_handoff import (
    ImprovementGoalHandoffReceipt,
    ImprovementGoalReceiptStatus,
)
from .improvement_signal import (
    ImprovementSignal,
    improvement_signal_subject_fingerprint,
)
from .improvement_signal_ledger import ImprovementSignalLedger


_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class ImprovementLineageFeedbackError(ValueError):
    """Verified Continuous Improvement lineage feedback failed."""


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ImprovementLineageFeedbackError(
            f"{field} is invalid"
        )
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ImprovementLineageFeedbackError(
            f"{field} must be lowercase SHA40"
        )
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ImprovementLineageFeedbackError(
            f"{field} must be sha256"
        )
    return value


def _evidence_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
        or value.startswith("/")
        or "\\" in value
        or _CONTROL.search(value)
    ):
        raise ImprovementLineageFeedbackError(
            "improvement retirement evidence path is unsafe"
        )
    path = PurePosixPath(value)
    if (
        "." in path.parts
        or ".." in path.parts
        or str(path) != value
        or not value.startswith(".autodev/")
    ):
        raise ImprovementLineageFeedbackError(
            "improvement retirement evidence path must remain inside .autodev/"
        )
    return value


def _lineage_ids(
    ledger: ImprovementSignalLedger,
    origin: ImprovementSignal,
) -> tuple[str, ...]:
    by_id = {
        signal.signal_id: signal
        for signal in ledger.signals
    }
    current = origin
    lineage: list[str] = [current.signal_id]
    seen = {current.signal_id}
    while current.parent_signal_id is not None:
        parent = by_id.get(current.parent_signal_id)
        if parent is None:
            raise ImprovementLineageFeedbackError(
                "originating improvement lineage parent is absent"
            )
        if parent.signal_id in seen:
            raise ImprovementLineageFeedbackError(
                "originating improvement lineage contains a cycle"
            )
        if (
            parent.repository != origin.repository
            or parent.source_sha != origin.source_sha
            or parent.release_candidate_id
            != origin.release_candidate_id
            or parent.release_environment
            != origin.release_environment
        ):
            raise ImprovementLineageFeedbackError(
                "originating improvement lineage crosses release identity"
            )
        seen.add(parent.signal_id)
        lineage.append(parent.signal_id)
        current = parent
    lineage.reverse()
    return tuple(lineage)


@dataclass(frozen=True, slots=True)
class ImprovementLineageRetirement:
    retirement_id: str
    release_candidate_id: str
    repository: str
    original_source_sha: str
    verified_source_sha: str
    origin_signal_id: str
    origin_signal_fingerprint: str
    subject_fingerprint: str
    retired_signal_ids: tuple[str, ...]
    bridge_fingerprint: str
    planning_goal_receipt_fingerprint: str
    backlog_retirement_id: str
    backlog_retirement_fingerprint: str
    campaign_id: str
    evidence_paths: tuple[str, ...]
    evidence_fingerprints: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementLineageFeedbackError(
                "unsupported improvement lineage retirement version"
            )
        for field in (
            "retirement_id",
            "release_candidate_id",
            "origin_signal_id",
            "backlog_retirement_id",
            "campaign_id",
        ):
            object.__setattr__(
                self,
                field,
                _identifier(getattr(self, field), field=field),
            )
        if (
            not isinstance(self.repository, str)
            or "/" not in self.repository
        ):
            raise ImprovementLineageFeedbackError(
                "repository must be owner/name"
            )
        object.__setattr__(
            self,
            "original_source_sha",
            _sha40(
                self.original_source_sha,
                field="original_source_sha",
            ),
        )
        object.__setattr__(
            self,
            "verified_source_sha",
            _sha40(
                self.verified_source_sha,
                field="verified_source_sha",
            ),
        )
        for field in (
            "origin_signal_fingerprint",
            "subject_fingerprint",
            "bridge_fingerprint",
            "planning_goal_receipt_fingerprint",
            "backlog_retirement_fingerprint",
        ):
            object.__setattr__(
                self,
                field,
                _sha256(getattr(self, field), field=field),
            )

        retired = tuple(self.retired_signal_ids)
        if (
            not retired
            or self.origin_signal_id not in retired
            or len(set(retired)) != len(retired)
        ):
            raise ImprovementLineageFeedbackError(
                "retired_signal_ids must uniquely include origin signal"
            )
        if any(
            not isinstance(signal_id, str)
            or _ID.fullmatch(signal_id) is None
            for signal_id in retired
        ):
            raise ImprovementLineageFeedbackError(
                "retired_signal_ids contain invalid identifier"
            )
        object.__setattr__(
            self,
            "retired_signal_ids",
            retired,
        )

        paths = tuple(_evidence_path(path) for path in self.evidence_paths)
        fingerprints = tuple(
            _sha256(value, field="evidence_fingerprint")
            for value in self.evidence_fingerprints
        )
        if (
            not paths
            or len(paths) != len(fingerprints)
            or len(paths) > 8
            or len(set(paths)) != len(paths)
        ):
            raise ImprovementLineageFeedbackError(
                "improvement retirement evidence is invalid"
            )
        object.__setattr__(self, "evidence_paths", paths)
        object.__setattr__(
            self,
            "evidence_fingerprints",
            fingerprints,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "retirement_id": self.retirement_id,
            "release_candidate_id": self.release_candidate_id,
            "repository": self.repository,
            "original_source_sha": self.original_source_sha,
            "verified_source_sha": self.verified_source_sha,
            "origin_signal_id": self.origin_signal_id,
            "origin_signal_fingerprint": (
                self.origin_signal_fingerprint
            ),
            "subject_fingerprint": self.subject_fingerprint,
            "retired_signal_ids": list(self.retired_signal_ids),
            "bridge_fingerprint": self.bridge_fingerprint,
            "planning_goal_receipt_fingerprint": (
                self.planning_goal_receipt_fingerprint
            ),
            "backlog_retirement_id": self.backlog_retirement_id,
            "backlog_retirement_fingerprint": (
                self.backlog_retirement_fingerprint
            ),
            "campaign_id": self.campaign_id,
            "evidence_paths": list(self.evidence_paths),
            "evidence_fingerprints": list(
                self.evidence_fingerprints
            ),
            "retirement_authority": (
                "trusted-verified-improvement-completion-v1"
            ),
            "planning_authority": False,
            "execution_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(
        cls,
        payload: object,
    ) -> "ImprovementLineageRetirement":
        if not isinstance(payload, dict):
            raise ImprovementLineageFeedbackError(
                "improvement lineage retirement must be a JSON object"
            )
        allowed = {
            "schema_version",
            "retirement_id",
            "release_candidate_id",
            "repository",
            "original_source_sha",
            "verified_source_sha",
            "origin_signal_id",
            "origin_signal_fingerprint",
            "subject_fingerprint",
            "retired_signal_ids",
            "bridge_fingerprint",
            "planning_goal_receipt_fingerprint",
            "backlog_retirement_id",
            "backlog_retirement_fingerprint",
            "campaign_id",
            "evidence_paths",
            "evidence_fingerprints",
            "retirement_authority",
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ImprovementLineageFeedbackError(
                "unknown improvement lineage retirement fields: "
                + str(sorted(unknown))
            )
        if payload.get("retirement_authority") != (
            "trusted-verified-improvement-completion-v1"
        ):
            raise ImprovementLineageFeedbackError(
                "improvement lineage retirement authority is invalid"
            )
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
        ):
            if payload.get(field, False) is not False:
                raise ImprovementLineageFeedbackError(
                    "improvement lineage retirement cannot grant "
                    + field.replace("_", " ")
                )
        raw_ids = payload.get("retired_signal_ids")
        raw_paths = payload.get("evidence_paths")
        raw_fingerprints = payload.get("evidence_fingerprints")
        if not isinstance(raw_ids, list):
            raise ImprovementLineageFeedbackError(
                "retired_signal_ids must be a list"
            )
        if (
            not isinstance(raw_paths, list)
            or not isinstance(raw_fingerprints, list)
        ):
            raise ImprovementLineageFeedbackError(
                "retirement evidence must be lists"
            )
        return cls(
            schema_version=payload.get("schema_version", 0),
            retirement_id=payload.get("retirement_id", ""),
            release_candidate_id=payload.get(
                "release_candidate_id",
                "",
            ),
            repository=payload.get("repository", ""),
            original_source_sha=payload.get(
                "original_source_sha",
                "",
            ),
            verified_source_sha=payload.get(
                "verified_source_sha",
                "",
            ),
            origin_signal_id=payload.get("origin_signal_id", ""),
            origin_signal_fingerprint=payload.get(
                "origin_signal_fingerprint",
                "",
            ),
            subject_fingerprint=payload.get(
                "subject_fingerprint",
                "",
            ),
            retired_signal_ids=tuple(str(x) for x in raw_ids),
            bridge_fingerprint=payload.get(
                "bridge_fingerprint",
                "",
            ),
            planning_goal_receipt_fingerprint=payload.get(
                "planning_goal_receipt_fingerprint",
                "",
            ),
            backlog_retirement_id=payload.get(
                "backlog_retirement_id",
                "",
            ),
            backlog_retirement_fingerprint=payload.get(
                "backlog_retirement_fingerprint",
                "",
            ),
            campaign_id=payload.get("campaign_id", ""),
            evidence_paths=tuple(str(x) for x in raw_paths),
            evidence_fingerprints=tuple(
                str(x) for x in raw_fingerprints
            ),
        )


def build_verified_improvement_lineage_retirement(
    *,
    ledger: ImprovementSignalLedger,
    bridge: ImprovementBridgeBundle,
    goal_receipt: ImprovementGoalHandoffReceipt,
    backlog: AutonomousBacklog,
    backlog_handoff: BacklogGoalHandoff,
    campaign_payload: object,
    state_payload: object,
    remote_execution_payload: object,
    runtime_contract_payload: object,
    runtime_receipt_payload: object,
    runtime_report_wrapper_payload: object,
    bridge_path: str,
    goal_receipt_path: str,
    backlog_handoff_path: str,
    campaign_path: str,
    state_path: str,
    remote_execution_path: str,
    runtime_contract_path: str,
    runtime_receipt_path: str,
    runtime_report_path: str,
    backlog_retirement_path: str,
) -> tuple[
    ImprovementLineageRetirement,
    BacklogRetirementRecord,
]:
    if not isinstance(ledger, ImprovementSignalLedger):
        raise ImprovementLineageFeedbackError(
            "ledger must be ImprovementSignalLedger"
        )
    if not isinstance(bridge, ImprovementBridgeBundle):
        raise ImprovementLineageFeedbackError(
            "bridge must be ImprovementBridgeBundle"
        )
    if not isinstance(
        goal_receipt,
        ImprovementGoalHandoffReceipt,
    ):
        raise ImprovementLineageFeedbackError(
            "goal_receipt must be ImprovementGoalHandoffReceipt"
        )
    if (
        goal_receipt.status
        is not ImprovementGoalReceiptStatus.HANDED_OFF
        or goal_receipt.handoff_count != 1
    ):
        raise ImprovementLineageFeedbackError(
            "verified improvement completion requires one HANDED_OFF PlanningGoal receipt"
        )
    if not isinstance(backlog_handoff, BacklogGoalHandoff):
        raise ImprovementLineageFeedbackError(
            "backlog_handoff must be BacklogGoalHandoff"
        )

    origin = ledger.signal_for(bridge.signal_id)
    if bridge.signal_fingerprint != origin.fingerprint():
        raise ImprovementLineageFeedbackError(
            "bridge signal fingerprint drift"
        )
    if (
        goal_receipt.signal_id != origin.signal_id
        or goal_receipt.signal_fingerprint != origin.fingerprint()
        or goal_receipt.bridge_fingerprint != bridge.fingerprint()
        or goal_receipt.release_candidate_id
        != origin.release_candidate_id
        or goal_receipt.backlog_candidate_id
        != bridge.backlog_candidate.candidate_id
        or goal_receipt.backlog_handoff_fingerprint
        != backlog_handoff.fingerprint()
        or goal_receipt.planning_request_fingerprint
        != backlog_handoff.request.fingerprint()
    ):
        raise ImprovementLineageFeedbackError(
            "PlanningGoal receipt does not bind originating improvement chain"
        )

    backlog_retirement = build_verified_backlog_retirement(
        backlog=backlog,
        handoff=backlog_handoff,
        campaign_payload=campaign_payload,
        state_payload=state_payload,
        remote_execution_payload=remote_execution_payload,
        runtime_contract_payload=runtime_contract_payload,
        runtime_receipt_payload=runtime_receipt_payload,
        runtime_report_wrapper_payload=runtime_report_wrapper_payload,
        handoff_path=backlog_handoff_path,
        campaign_path=campaign_path,
        state_path=state_path,
        remote_execution_path=remote_execution_path,
        runtime_contract_path=runtime_contract_path,
        runtime_receipt_path=runtime_receipt_path,
        runtime_report_path=runtime_report_path,
    )
    if (
        backlog_retirement.candidate_id
        != bridge.backlog_candidate.candidate_id
        or backlog_retirement.candidate_fingerprint
        != bridge.backlog_candidate.fingerprint()
        or backlog_retirement.goal_handoff_fingerprint
        != backlog_handoff.fingerprint()
        or backlog_retirement.request_id
        != backlog_handoff.request.request_id
        or backlog_retirement.campaign_id
        != backlog_handoff.request.campaign_id
        or backlog_retirement.repository != origin.repository
        or backlog_retirement.original_source_sha
        != origin.source_sha
    ):
        raise ImprovementLineageFeedbackError(
            "verified Backlog retirement does not bind originating improvement chain"
        )

    retired_signal_ids = _lineage_ids(ledger, origin)
    subject_fingerprint = improvement_signal_subject_fingerprint(
        origin
    )
    evidence_paths = (
        _evidence_path(bridge_path),
        _evidence_path(goal_receipt_path),
        _evidence_path(backlog_retirement_path),
    )
    evidence_fingerprints = (
        bridge.fingerprint(),
        goal_receipt.fingerprint(),
        backlog_retirement.fingerprint(),
    )
    identity = _fingerprint(
        {
            "release_candidate_id": origin.release_candidate_id,
            "origin_signal_id": origin.signal_id,
            "origin_signal_fingerprint": origin.fingerprint(),
            "subject_fingerprint": subject_fingerprint,
            "retired_signal_ids": list(retired_signal_ids),
            "bridge_fingerprint": bridge.fingerprint(),
            "planning_goal_receipt_fingerprint": (
                goal_receipt.fingerprint()
            ),
            "backlog_retirement_fingerprint": (
                backlog_retirement.fingerprint()
            ),
            "verified_source_sha": (
                backlog_retirement.verified_source_sha
            ),
        }
    )
    return (
        ImprovementLineageRetirement(
            retirement_id=(
                "improvement-retire-" + identity[:24]
            ),
            release_candidate_id=origin.release_candidate_id,
            repository=origin.repository,
            original_source_sha=origin.source_sha,
            verified_source_sha=(
                backlog_retirement.verified_source_sha
            ),
            origin_signal_id=origin.signal_id,
            origin_signal_fingerprint=origin.fingerprint(),
            subject_fingerprint=subject_fingerprint,
            retired_signal_ids=retired_signal_ids,
            bridge_fingerprint=bridge.fingerprint(),
            planning_goal_receipt_fingerprint=(
                goal_receipt.fingerprint()
            ),
            backlog_retirement_id=(
                backlog_retirement.retirement_id
            ),
            backlog_retirement_fingerprint=(
                backlog_retirement.fingerprint()
            ),
            campaign_id=backlog_retirement.campaign_id,
            evidence_paths=evidence_paths,
            evidence_fingerprints=evidence_fingerprints,
        ),
        backlog_retirement,
    )
