from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DecisionPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    decision_id: str
    question: str
    options: tuple[str, ...]
    priority: DecisionPriority
    blocking_task_id: str
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, str) or not self.decision_id.strip():
            raise ValueError("decision_id must be a non-empty string")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be a non-empty string")
        if not isinstance(self.blocking_task_id, str) or not self.blocking_task_id.strip():
            raise ValueError("blocking_task_id must be a non-empty string")

        try:
            priority_enum = DecisionPriority(self.priority)
        except (ValueError, TypeError):
            raise ValueError(f"invalid priority: {self.priority}")
        object.__setattr__(self, "priority", priority_enum)

        if isinstance(self.options, (list, tuple)):
            opts = tuple(self.options)
        else:
            try:
                opts = tuple(self.options)
            except TypeError:
                raise ValueError("options must be an iterable of strings")

        for opt in opts:
            if not isinstance(opt, str) or not opt.strip():
                raise ValueError("options must contain non-empty strings")

        if len(set(opts)) < 2:
            raise ValueError("options must contain at least two unique non-empty strings")

        object.__setattr__(self, "options", opts)

        if not isinstance(self.context, dict):
            raise ValueError("context must be a dict")
        object.__setattr__(self, "context", dict(self.context))
