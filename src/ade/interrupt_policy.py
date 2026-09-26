from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DecisionKind(StrEnum):
    DESTRUCTIVE_OR_IRREVERSIBLE = "destructive_or_irreversible"
    CREDENTIAL_OR_SECRET = "credential_or_secret"
    EXTERNAL_SIDE_EFFECT = "external_side_effect"
    SPECIFICATION_AMBIGUITY = "specification_ambiguity"
    USER_PREFERENCE = "user_preference"
    ROUTINE_REVERSIBLE = "routine_reversible"


class InterruptDisposition(StrEnum):
    PROCEED = "PROCEED"
    HUMAN_WAIT = "HUMAN_WAIT"


_FIXED_DISPOSITIONS: dict[DecisionKind, InterruptDisposition] = {
    DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE: InterruptDisposition.HUMAN_WAIT,
    DecisionKind.CREDENTIAL_OR_SECRET: InterruptDisposition.HUMAN_WAIT,
    DecisionKind.EXTERNAL_SIDE_EFFECT: InterruptDisposition.HUMAN_WAIT,
    DecisionKind.ROUTINE_REVERSIBLE: InterruptDisposition.PROCEED,
}


@dataclass(frozen=True, slots=True)
class InterruptPolicy:
    """Deterministic policy for deciding whether work may continue autonomously."""

    specification_ambiguity: InterruptDisposition = InterruptDisposition.HUMAN_WAIT
    user_preference: InterruptDisposition = InterruptDisposition.HUMAN_WAIT

    def __post_init__(self) -> None:
        try:
            ambiguity = InterruptDisposition(self.specification_ambiguity)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"invalid specification_ambiguity disposition: {self.specification_ambiguity}"
            ) from exc
        try:
            preference = InterruptDisposition(self.user_preference)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"invalid user_preference disposition: {self.user_preference}"
            ) from exc

        object.__setattr__(self, "specification_ambiguity", ambiguity)
        object.__setattr__(self, "user_preference", preference)

    def decide(self, kind: DecisionKind | str) -> InterruptDisposition:
        try:
            resolved_kind = DecisionKind(kind)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid decision kind: {kind}") from exc

        fixed = _FIXED_DISPOSITIONS.get(resolved_kind)
        if fixed is not None:
            return fixed

        if resolved_kind is DecisionKind.SPECIFICATION_AMBIGUITY:
            return self.specification_ambiguity
        if resolved_kind is DecisionKind.USER_PREFERENCE:
            return self.user_preference

        raise ValueError(f"unhandled decision kind: {resolved_kind}")


def decide_interrupt(
    kind: DecisionKind | str,
    *,
    policy: InterruptPolicy | None = None,
) -> InterruptDisposition:
    resolved_policy = policy if policy is not None else InterruptPolicy()
    if not isinstance(resolved_policy, InterruptPolicy):
        raise ValueError("policy must be an InterruptPolicy or None")
    return resolved_policy.decide(kind)
