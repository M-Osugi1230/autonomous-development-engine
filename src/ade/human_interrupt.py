from __future__ import annotations

from .decision_store import DecisionStore
from .decisions import (
    DecisionRecord,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
)
from .interrupt_policy import (
    DecisionKind,
    InterruptDisposition,
    InterruptPolicy,
)


class HumanInterruptCoordinator:
    """Coordinates deterministic human interrupts without performing network I/O."""

    def __init__(
        self,
        store: DecisionStore,
        *,
        policy: InterruptPolicy | None = None,
    ) -> None:
        if not isinstance(store, DecisionStore):
            raise ValueError("store must be a DecisionStore")
        if policy is None:
            resolved_policy = InterruptPolicy()
        elif isinstance(policy, InterruptPolicy):
            resolved_policy = policy
        else:
            raise ValueError("policy must be an InterruptPolicy or None")

        self._store = store
        self._policy = resolved_policy

    @property
    def policy(self) -> InterruptPolicy:
        return self._policy

    def request_decision(
        self,
        kind: DecisionKind | str,
        request: DecisionRequest,
    ) -> InterruptDisposition:
        if not isinstance(request, DecisionRequest):
            raise ValueError("request must be a DecisionRequest")

        existing = self._store.get(request.decision_id)
        if existing is not None:
            if existing.request != request:
                raise ValueError(
                    f"decision_id conflict for existing request: {request.decision_id}"
                )
            if existing.status is DecisionStatus.OPEN:
                return InterruptDisposition.HUMAN_WAIT
            if existing.status is DecisionStatus.RESOLVED:
                raise ValueError(
                    f"decision {request.decision_id} is already resolved; "
                    "retrieve the human response explicitly"
                )
            if existing.status is DecisionStatus.CANCELLED:
                raise ValueError(
                    f"decision {request.decision_id} is cancelled and cannot auto-proceed"
                )
            raise ValueError(f"unhandled decision status: {existing.status}")

        disposition = self._policy.decide(kind)
        if disposition is InterruptDisposition.PROCEED:
            return disposition

        if disposition is InterruptDisposition.HUMAN_WAIT:
            self._store.enqueue(DecisionRecord(request=request))
            return disposition

        raise ValueError(f"unhandled interrupt disposition: {disposition}")

    def resolve(
        self,
        decision_id: str,
        response: DecisionResponse,
    ) -> DecisionRecord:
        if not isinstance(response, DecisionResponse):
            raise ValueError("response must be a DecisionResponse")
        if response.decision_id != decision_id:
            raise ValueError("response decision_id does not match decision_id")
        return self._store.resolve(decision_id, response)

    def get_resolved_response(
        self,
        decision_id: str,
    ) -> DecisionResponse | None:
        record = self._store.get(decision_id)
        if record is None:
            return None
        if record.status is not DecisionStatus.RESOLVED:
            return None
        if record.response is None:
            raise RuntimeError("resolved decision is missing its response")
        return record.response
