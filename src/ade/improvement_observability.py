from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from .improvement_goal_handoff import (
    ImprovementGoalHandoffReceipt,
    ImprovementGoalReceiptStatus,
)
from .improvement_lineage_feedback import (
    ImprovementLineageRetirement,
)
from .improvement_signal_ledger import ImprovementSignalLedger
from .improvement_signal_resolution import (
    ImprovementResolutionState,
    ImprovementSignalResolution,
)


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ImprovementObservabilityError(ValueError):
    """Safe Continuous Improvement observability validation failed."""


class ImprovementCycleViewState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    ARMED = "ARMED"
    HANDED_OFF = "HANDED_OFF"
    VERIFIED_RETIRED = "VERIFIED_RETIRED"


@dataclass(frozen=True, slots=True)
class ImprovementObservabilitySnapshot:
    release_candidate_id: str
    repository: str
    source_sha: str
    release_environment: str
    signal_count: int
    observation_only_count: int
    current_count: int
    cooldown_count: int
    superseded_count: int
    conflicted_count: int
    cycle_limit_count: int
    retired_count: int
    current_signal_id: str | None
    current_signal_kind: str | None
    cycle_state: ImprovementCycleViewState
    cycle_index: int | None
    handoff_count: int
    lineage_retirement_count: int
    latest_retirement_id: str | None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementObservabilityError(
                "unsupported improvement observability schema version"
            )
        if (
            not isinstance(self.release_candidate_id, str)
            or _ID.fullmatch(self.release_candidate_id) is None
        ):
            raise ImprovementObservabilityError(
                "release_candidate_id is invalid"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise ImprovementObservabilityError(
                "repository must be owner/name"
            )
        if (
            not isinstance(self.source_sha, str)
            or _SHA40.fullmatch(self.source_sha) is None
        ):
            raise ImprovementObservabilityError(
                "source_sha must be lowercase SHA40"
            )
        if self.release_environment not in {
            "preview",
            "staging",
            "production",
        }:
            raise ImprovementObservabilityError(
                "release_environment is invalid"
            )

        count_fields = (
            "signal_count",
            "observation_only_count",
            "current_count",
            "cooldown_count",
            "superseded_count",
            "conflicted_count",
            "cycle_limit_count",
            "retired_count",
            "handoff_count",
            "lineage_retirement_count",
        )
        for field in count_fields:
            value = getattr(self, field)
            if type(value) is not int or value < 0:
                raise ImprovementObservabilityError(
                    f"{field} must be a non-negative integer"
                )

        resolved_total = (
            self.observation_only_count
            + self.current_count
            + self.cooldown_count
            + self.superseded_count
            + self.conflicted_count
            + self.cycle_limit_count
            + self.retired_count
        )
        if resolved_total != self.signal_count:
            raise ImprovementObservabilityError(
                "improvement state counts do not sum to signal_count"
            )
        if self.current_count not in {0, 1}:
            raise ImprovementObservabilityError(
                "current_count must be zero or one"
            )

        has_current_identity = (
            self.current_signal_id is not None
            or self.current_signal_kind is not None
        )
        if self.current_count == 1:
            if (
                not isinstance(self.current_signal_id, str)
                or _ID.fullmatch(self.current_signal_id) is None
                or not isinstance(self.current_signal_kind, str)
                or not self.current_signal_kind
            ):
                raise ImprovementObservabilityError(
                    "CURRENT signal requires safe id and kind"
                )
        elif has_current_identity:
            raise ImprovementObservabilityError(
                "CURRENT signal identity requires current_count 1"
            )

        if not isinstance(self.cycle_state, ImprovementCycleViewState):
            try:
                object.__setattr__(
                    self,
                    "cycle_state",
                    ImprovementCycleViewState(self.cycle_state),
                )
            except (TypeError, ValueError) as exc:
                raise ImprovementObservabilityError(
                    "cycle_state is invalid"
                ) from exc

        if self.cycle_state is ImprovementCycleViewState.NOT_STARTED:
            if self.cycle_index is not None or self.handoff_count != 0:
                raise ImprovementObservabilityError(
                    "NOT_STARTED cycle cannot have index or handoff"
                )
        else:
            if type(self.cycle_index) is not int or self.cycle_index < 1:
                raise ImprovementObservabilityError(
                    "active improvement cycle requires positive cycle_index"
                )
            expected_handoffs = (
                0
                if self.cycle_state is ImprovementCycleViewState.ARMED
                else 1
            )
            if self.handoff_count != expected_handoffs:
                raise ImprovementObservabilityError(
                    "cycle handoff_count does not match cycle_state"
                )

        if self.lineage_retirement_count == 0:
            if self.latest_retirement_id is not None:
                raise ImprovementObservabilityError(
                    "latest_retirement_id requires retirement"
                )
        else:
            if (
                not isinstance(self.latest_retirement_id, str)
                or _ID.fullmatch(self.latest_retirement_id) is None
            ):
                raise ImprovementObservabilityError(
                    "retirement count requires safe latest_retirement_id"
                )
        if (
            self.cycle_state
            is ImprovementCycleViewState.VERIFIED_RETIRED
            and self.lineage_retirement_count == 0
        ):
            raise ImprovementObservabilityError(
                "VERIFIED_RETIRED cycle requires lineage retirement"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "release_candidate_id": self.release_candidate_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "release_environment": self.release_environment,
            "signal_count": self.signal_count,
            "observation_only_count": self.observation_only_count,
            "current_count": self.current_count,
            "cooldown_count": self.cooldown_count,
            "superseded_count": self.superseded_count,
            "conflicted_count": self.conflicted_count,
            "cycle_limit_count": self.cycle_limit_count,
            "retired_count": self.retired_count,
            "current_signal_id": self.current_signal_id,
            "current_signal_kind": self.current_signal_kind,
            "cycle_state": self.cycle_state.value,
            "cycle_index": self.cycle_index,
            "handoff_count": self.handoff_count,
            "lineage_retirement_count": (
                self.lineage_retirement_count
            ),
            "latest_retirement_id": self.latest_retirement_id,
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "ImprovementObservabilitySnapshot":
        if not isinstance(payload, dict):
            raise ImprovementObservabilityError(
                "improvement observability snapshot must be a JSON object"
            )
        allowed = {
            "schema_version",
            "release_candidate_id",
            "repository",
            "source_sha",
            "release_environment",
            "signal_count",
            "observation_only_count",
            "current_count",
            "cooldown_count",
            "superseded_count",
            "conflicted_count",
            "cycle_limit_count",
            "retired_count",
            "current_signal_id",
            "current_signal_kind",
            "cycle_state",
            "cycle_index",
            "handoff_count",
            "lineage_retirement_count",
            "latest_retirement_id",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ImprovementObservabilityError(
                "unknown improvement observability fields: "
                + str(sorted(unknown))
            )
        try:
            cycle_state = ImprovementCycleViewState(
                payload.get("cycle_state")
            )
        except (TypeError, ValueError) as exc:
            raise ImprovementObservabilityError(
                "cycle_state is invalid"
            ) from exc
        return cls(
            schema_version=payload.get("schema_version", 0),
            release_candidate_id=payload.get(
                "release_candidate_id",
                "",
            ),
            repository=payload.get("repository", ""),
            source_sha=payload.get("source_sha", ""),
            release_environment=payload.get(
                "release_environment",
                "",
            ),
            signal_count=payload.get("signal_count", -1),
            observation_only_count=payload.get(
                "observation_only_count",
                -1,
            ),
            current_count=payload.get("current_count", -1),
            cooldown_count=payload.get("cooldown_count", -1),
            superseded_count=payload.get(
                "superseded_count",
                -1,
            ),
            conflicted_count=payload.get("conflicted_count", -1),
            cycle_limit_count=payload.get(
                "cycle_limit_count",
                -1,
            ),
            retired_count=payload.get("retired_count", -1),
            current_signal_id=payload.get("current_signal_id"),
            current_signal_kind=payload.get("current_signal_kind"),
            cycle_state=cycle_state,
            cycle_index=payload.get("cycle_index"),
            handoff_count=payload.get("handoff_count", -1),
            lineage_retirement_count=payload.get(
                "lineage_retirement_count",
                -1,
            ),
            latest_retirement_id=payload.get(
                "latest_retirement_id"
            ),
        )


def build_improvement_observability_snapshot(
    *,
    ledger: ImprovementSignalLedger,
    resolution: ImprovementSignalResolution,
    release_candidate_id: str,
    goal_receipt: ImprovementGoalHandoffReceipt | None = None,
    retirements: tuple[ImprovementLineageRetirement, ...] = (),
) -> ImprovementObservabilitySnapshot:
    if not isinstance(ledger, ImprovementSignalLedger):
        raise ImprovementObservabilityError(
            "ledger must be ImprovementSignalLedger"
        )
    if not isinstance(
        resolution,
        ImprovementSignalResolution,
    ):
        raise ImprovementObservabilityError(
            "resolution must be ImprovementSignalResolution"
        )
    if resolution.ledger_fingerprint != ledger.fingerprint():
        raise ImprovementObservabilityError(
            "resolution does not bind supplied signal ledger"
        )
    if (
        not isinstance(release_candidate_id, str)
        or _ID.fullmatch(release_candidate_id) is None
    ):
        raise ImprovementObservabilityError(
            "release_candidate_id is invalid"
        )

    selected = tuple(
        signal
        for signal in ledger.signals
        if signal.release_candidate_id == release_candidate_id
    )
    if not selected:
        raise ImprovementObservabilityError(
            "release candidate has no improvement signals"
        )
    identities = {
        (
            signal.repository,
            signal.source_sha,
            signal.release_environment,
        )
        for signal in selected
    }
    if len(identities) != 1:
        raise ImprovementObservabilityError(
            "release candidate improvement identity drift"
        )
    repository, source_sha, environment = next(iter(identities))

    state_counts = {
        state: 0
        for state in ImprovementResolutionState
    }
    current_signal = None
    for signal in selected:
        entry = resolution.entry_for(signal.signal_id)
        state_counts[entry.state] += 1
        if entry.state is ImprovementResolutionState.CURRENT:
            if current_signal is not None:
                raise ImprovementObservabilityError(
                    "multiple CURRENT signals cannot be observed"
                )
            current_signal = signal

    matching_retirements = tuple(
        item
        for item in retirements
        if item.release_candidate_id == release_candidate_id
    )
    expected_retirement_fingerprints = {
        item.fingerprint()
        for item in matching_retirements
    }
    if not expected_retirement_fingerprints.issubset(
        set(resolution.retirement_fingerprints)
    ):
        raise ImprovementObservabilityError(
            "retirement projection is not bound to resolution"
        )
    if any(
        item.repository != repository
        or item.original_source_sha != source_sha
        for item in matching_retirements
    ):
        raise ImprovementObservabilityError(
            "retirement release identity drift"
        )

    if goal_receipt is None:
        cycle_state = ImprovementCycleViewState.NOT_STARTED
        cycle_index = None
        handoff_count = 0
    else:
        if not isinstance(
            goal_receipt,
            ImprovementGoalHandoffReceipt,
        ):
            raise ImprovementObservabilityError(
                "goal_receipt must be ImprovementGoalHandoffReceipt or null"
            )
        if goal_receipt.release_candidate_id != release_candidate_id:
            raise ImprovementObservabilityError(
                "PlanningGoal receipt release identity drift"
            )
        if goal_receipt.signal_id not in {
            signal.signal_id for signal in selected
        }:
            raise ImprovementObservabilityError(
                "PlanningGoal receipt signal is absent from release"
            )
        cycle_index = goal_receipt.cycle_index
        handoff_count = goal_receipt.handoff_count
        if (
            goal_receipt.status
            is ImprovementGoalReceiptStatus.ARMED
        ):
            cycle_state = ImprovementCycleViewState.ARMED
        else:
            retired_ids = {
                signal_id
                for item in matching_retirements
                for signal_id in item.retired_signal_ids
            }
            cycle_state = (
                ImprovementCycleViewState.VERIFIED_RETIRED
                if goal_receipt.signal_id in retired_ids
                else ImprovementCycleViewState.HANDED_OFF
            )

    latest_retirement_id = (
        sorted(
            item.retirement_id
            for item in matching_retirements
        )[-1]
        if matching_retirements
        else None
    )
    return ImprovementObservabilitySnapshot(
        release_candidate_id=release_candidate_id,
        repository=repository,
        source_sha=source_sha,
        release_environment=environment,
        signal_count=len(selected),
        observation_only_count=state_counts[
            ImprovementResolutionState.OBSERVATION_ONLY
        ],
        current_count=state_counts[
            ImprovementResolutionState.CURRENT
        ],
        cooldown_count=state_counts[
            ImprovementResolutionState.COOLDOWN
        ],
        superseded_count=state_counts[
            ImprovementResolutionState.SUPERSEDED
        ],
        conflicted_count=state_counts[
            ImprovementResolutionState.CONFLICTED
        ],
        cycle_limit_count=state_counts[
            ImprovementResolutionState.CYCLE_LIMIT
        ],
        retired_count=state_counts[
            ImprovementResolutionState.RETIRED
        ],
        current_signal_id=(
            current_signal.signal_id
            if current_signal is not None
            else None
        ),
        current_signal_kind=(
            current_signal.kind.value
            if current_signal is not None
            else None
        ),
        cycle_state=cycle_state,
        cycle_index=cycle_index,
        handoff_count=handoff_count,
        lineage_retirement_count=len(matching_retirements),
        latest_retirement_id=latest_retirement_id,
    )
