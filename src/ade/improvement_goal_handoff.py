from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any

from .autonomous_backlog import AutonomousBacklog
from .autonomous_backlog_goal import (
    BacklogGoalHandoff,
    BacklogPlanningPolicy,
    build_planning_goal_handoff,
)
from .autonomous_backlog_resolution import (
    AutonomousBacklogResolution,
)
from .autonomous_backlog_selection import BacklogSelection
from .improvement_bridge import (
    ImprovementBridgeBundle,
)
from .improvement_signal_ledger import (
    ImprovementSignalLedger,
)
from .improvement_signal_resolution import (
    ImprovementResolutionState,
    ImprovementSignalResolution,
)


class ImprovementGoalHandoffError(ValueError):
    """Continuous Improvement PlanningGoal handoff failed."""


class ImprovementGoalReceiptStatus(StrEnum):
    ARMED = "ARMED"
    HANDED_OFF = "HANDED_OFF"


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


@dataclass(frozen=True, slots=True)
class ImprovementCyclePolicy:
    max_cycles: int = 4
    max_goal_handoffs_per_cycle: int = 1
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementGoalHandoffError(
                "unsupported improvement cycle policy version"
            )
        if type(self.max_cycles) is not int or not (
            1 <= self.max_cycles <= 16
        ):
            raise ImprovementGoalHandoffError(
                "max_cycles must be between 1 and 16"
            )
        if self.max_goal_handoffs_per_cycle != 1:
            raise ImprovementGoalHandoffError(
                "current safety policy allows exactly one PlanningGoal handoff per cycle"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "max_cycles": self.max_cycles,
            "max_goal_handoffs_per_cycle": 1,
            "planning_goal_source": (
                "trusted-autonomous-backlog-handoff-v1"
            ),
            "execution_authority": False,
            "accepted_plan_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ImprovementGoalHandoffReceipt:
    cycle_id: str
    cycle_index: int
    release_candidate_id: str
    signal_id: str
    signal_fingerprint: str
    bridge_fingerprint: str
    backlog_candidate_id: str
    backlog_handoff_fingerprint: str
    planning_request_fingerprint: str
    cycle_policy_fingerprint: str
    status: ImprovementGoalReceiptStatus
    handoff_count: int
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementGoalHandoffError(
                "unsupported improvement handoff receipt version"
            )
        for field in (
            "cycle_id",
            "release_candidate_id",
            "signal_id",
            "backlog_candidate_id",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise ImprovementGoalHandoffError(
                    f"{field} must be non-empty"
                )
        for field in (
            "signal_fingerprint",
            "bridge_fingerprint",
            "backlog_handoff_fingerprint",
            "planning_request_fingerprint",
            "cycle_policy_fingerprint",
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    char not in "0123456789abcdef"
                    for char in value
                )
            ):
                raise ImprovementGoalHandoffError(
                    f"{field} must be sha256"
                )
        if type(self.cycle_index) is not int or self.cycle_index < 1:
            raise ImprovementGoalHandoffError(
                "cycle_index must be positive"
            )
        if not isinstance(
            self.status,
            ImprovementGoalReceiptStatus,
        ):
            object.__setattr__(
                self,
                "status",
                ImprovementGoalReceiptStatus(self.status),
            )
        if self.status is ImprovementGoalReceiptStatus.ARMED:
            if self.handoff_count != 0:
                raise ImprovementGoalHandoffError(
                    "ARMED receipt requires handoff_count 0"
                )
        elif self.status is ImprovementGoalReceiptStatus.HANDED_OFF:
            if self.handoff_count != 1:
                raise ImprovementGoalHandoffError(
                    "HANDED_OFF receipt requires handoff_count 1"
                )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "cycle_id": self.cycle_id,
            "cycle_index": self.cycle_index,
            "release_candidate_id": self.release_candidate_id,
            "signal_id": self.signal_id,
            "signal_fingerprint": self.signal_fingerprint,
            "bridge_fingerprint": self.bridge_fingerprint,
            "backlog_candidate_id": self.backlog_candidate_id,
            "backlog_handoff_fingerprint": (
                self.backlog_handoff_fingerprint
            ),
            "planning_request_fingerprint": (
                self.planning_request_fingerprint
            ),
            "cycle_policy_fingerprint": (
                self.cycle_policy_fingerprint
            ),
            "status": self.status.value,
            "handoff_count": self.handoff_count,
            "execution_authority": False,
            "accepted_plan_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ImprovementPlanningGoalActivation:
    backlog_handoff: BacklogGoalHandoff
    receipt: ImprovementGoalHandoffReceipt
    should_handoff: bool
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ImprovementGoalHandoffError(
                "unsupported improvement PlanningGoal activation version"
            )
        if not isinstance(self.backlog_handoff, BacklogGoalHandoff):
            raise ImprovementGoalHandoffError(
                "backlog_handoff must be BacklogGoalHandoff"
            )
        if not isinstance(
            self.receipt,
            ImprovementGoalHandoffReceipt,
        ):
            raise ImprovementGoalHandoffError(
                "receipt must be ImprovementGoalHandoffReceipt"
            )
        expected = (
            self.receipt.status
            is ImprovementGoalReceiptStatus.ARMED
        )
        if self.should_handoff != expected:
            raise ImprovementGoalHandoffError(
                "PlanningGoal handoff state drift"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "backlog_handoff": (
                self.backlog_handoff.canonical_dict()
            ),
            "backlog_handoff_fingerprint": (
                self.backlog_handoff.fingerprint()
            ),
            "receipt": self.receipt.canonical_dict(),
            "should_handoff": self.should_handoff,
            "handoff_target": "AutonomousPlanner",
            "execution_authority": False,
            "accepted_plan_authority": False,
            "auto_dispatch": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def _cycle_id(
    *,
    release_candidate_id: str,
    cycle_index: int,
    policy_fingerprint: str,
) -> str:
    digest = _fingerprint(
        {
            "release_candidate_id": release_candidate_id,
            "cycle_index": cycle_index,
            "cycle_policy_fingerprint": policy_fingerprint,
        }
    )
    return "improvement-cycle-" + digest[:24]


def _receipt_identity_matches(
    left: ImprovementGoalHandoffReceipt,
    right: ImprovementGoalHandoffReceipt,
) -> bool:
    return (
        left.cycle_id == right.cycle_id
        and left.cycle_index == right.cycle_index
        and left.release_candidate_id == right.release_candidate_id
        and left.signal_id == right.signal_id
        and left.signal_fingerprint == right.signal_fingerprint
        and left.bridge_fingerprint == right.bridge_fingerprint
        and left.backlog_candidate_id == right.backlog_candidate_id
        and left.backlog_handoff_fingerprint
        == right.backlog_handoff_fingerprint
        and left.planning_request_fingerprint
        == right.planning_request_fingerprint
        and left.cycle_policy_fingerprint
        == right.cycle_policy_fingerprint
    )


def arm_improvement_planning_goal_handoff(
    *,
    ledger: ImprovementSignalLedger,
    improvement_resolution: ImprovementSignalResolution,
    bridge: ImprovementBridgeBundle,
    backlog: AutonomousBacklog,
    backlog_resolution: AutonomousBacklogResolution,
    selection: BacklogSelection,
    backlog_policy: BacklogPlanningPolicy,
    cycle_index: int,
    cycle_policy: ImprovementCyclePolicy | None = None,
    existing_receipt: ImprovementGoalHandoffReceipt | None = None,
) -> ImprovementPlanningGoalActivation:
    if not isinstance(ledger, ImprovementSignalLedger):
        raise ImprovementGoalHandoffError(
            "ledger must be ImprovementSignalLedger"
        )
    if not isinstance(
        improvement_resolution,
        ImprovementSignalResolution,
    ):
        raise ImprovementGoalHandoffError(
            "improvement_resolution must be ImprovementSignalResolution"
        )
    if not isinstance(bridge, ImprovementBridgeBundle):
        raise ImprovementGoalHandoffError(
            "bridge must be ImprovementBridgeBundle"
        )
    if improvement_resolution.ledger_fingerprint != ledger.fingerprint():
        raise ImprovementGoalHandoffError(
            "improvement resolution does not bind supplied ledger"
        )
    signal = ledger.signal_for(bridge.signal_id)
    entry = improvement_resolution.entry_for(signal.signal_id)
    if entry.state is not ImprovementResolutionState.CURRENT:
        raise ImprovementGoalHandoffError(
            "PlanningGoal handoff requires CURRENT improvement signal"
        )
    if bridge.signal_fingerprint != signal.fingerprint():
        raise ImprovementGoalHandoffError(
            "bridge signal fingerprint drift"
        )
    if (
        bridge.resolution_fingerprint
        != improvement_resolution.fingerprint()
    ):
        raise ImprovementGoalHandoffError(
            "bridge resolution fingerprint drift"
        )

    candidate_by_id = {
        item.candidate_id: item
        for item in backlog.candidates
    }
    candidate = candidate_by_id.get(
        bridge.backlog_candidate.candidate_id
    )
    if (
        candidate is None
        or candidate.canonical_dict()
        != bridge.backlog_candidate.canonical_dict()
    ):
        raise ImprovementGoalHandoffError(
            "bridge backlog candidate is missing or drifted"
        )
    if (
        selection.selected_candidate_id
        != bridge.backlog_candidate.candidate_id
    ):
        raise ImprovementGoalHandoffError(
            "existing Backlog selection did not choose bridged candidate"
        )

    cycle_policy = cycle_policy or ImprovementCyclePolicy()
    if not isinstance(cycle_policy, ImprovementCyclePolicy):
        raise ImprovementGoalHandoffError(
            "cycle_policy must be ImprovementCyclePolicy"
        )
    if type(cycle_index) is not int or not (
        1 <= cycle_index <= cycle_policy.max_cycles
    ):
        raise ImprovementGoalHandoffError(
            "cycle_index exceeds trusted improvement cycle budget"
        )

    backlog_handoff = build_planning_goal_handoff(
        backlog,
        backlog_resolution,
        selection,
        policy=backlog_policy,
    )
    if (
        backlog_handoff.candidate_id
        != bridge.backlog_candidate.candidate_id
    ):
        raise ImprovementGoalHandoffError(
            "Backlog Goal handoff candidate drift"
        )

    policy_fingerprint = cycle_policy.fingerprint()
    expected = ImprovementGoalHandoffReceipt(
        cycle_id=_cycle_id(
            release_candidate_id=signal.release_candidate_id,
            cycle_index=cycle_index,
            policy_fingerprint=policy_fingerprint,
        ),
        cycle_index=cycle_index,
        release_candidate_id=signal.release_candidate_id,
        signal_id=signal.signal_id,
        signal_fingerprint=signal.fingerprint(),
        bridge_fingerprint=bridge.fingerprint(),
        backlog_candidate_id=bridge.backlog_candidate.candidate_id,
        backlog_handoff_fingerprint=backlog_handoff.fingerprint(),
        planning_request_fingerprint=(
            backlog_handoff.request.fingerprint()
        ),
        cycle_policy_fingerprint=policy_fingerprint,
        status=ImprovementGoalReceiptStatus.ARMED,
        handoff_count=0,
    )

    if existing_receipt is None:
        receipt = expected
    else:
        if not isinstance(
            existing_receipt,
            ImprovementGoalHandoffReceipt,
        ):
            raise ImprovementGoalHandoffError(
                "existing_receipt must be ImprovementGoalHandoffReceipt or null"
            )
        if not _receipt_identity_matches(
            existing_receipt,
            expected,
        ):
            raise ImprovementGoalHandoffError(
                "existing PlanningGoal receipt identity drift"
            )
        receipt = existing_receipt

    return ImprovementPlanningGoalActivation(
        backlog_handoff=backlog_handoff,
        receipt=receipt,
        should_handoff=(
            receipt.status is ImprovementGoalReceiptStatus.ARMED
        ),
    )


def record_improvement_planning_goal_handoff(
    activation: ImprovementPlanningGoalActivation,
) -> ImprovementGoalHandoffReceipt:
    if not isinstance(
        activation,
        ImprovementPlanningGoalActivation,
    ):
        raise ImprovementGoalHandoffError(
            "activation must be ImprovementPlanningGoalActivation"
        )
    receipt = activation.receipt
    if receipt.status is ImprovementGoalReceiptStatus.HANDED_OFF:
        return receipt
    return ImprovementGoalHandoffReceipt(
        cycle_id=receipt.cycle_id,
        cycle_index=receipt.cycle_index,
        release_candidate_id=receipt.release_candidate_id,
        signal_id=receipt.signal_id,
        signal_fingerprint=receipt.signal_fingerprint,
        bridge_fingerprint=receipt.bridge_fingerprint,
        backlog_candidate_id=receipt.backlog_candidate_id,
        backlog_handoff_fingerprint=(
            receipt.backlog_handoff_fingerprint
        ),
        planning_request_fingerprint=(
            receipt.planning_request_fingerprint
        ),
        cycle_policy_fingerprint=(
            receipt.cycle_policy_fingerprint
        ),
        status=ImprovementGoalReceiptStatus.HANDED_OFF,
        handoff_count=1,
    )
