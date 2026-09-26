from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DecisionPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class DecisionStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


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
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid priority: {self.priority}") from exc
        object.__setattr__(self, "priority", priority_enum)

        if isinstance(self.options, (list, tuple)):
            opts = tuple(self.options)
        else:
            try:
                opts = tuple(self.options)
            except TypeError as exc:
                raise ValueError("options must be an iterable of strings") from exc

        for opt in opts:
            if not isinstance(opt, str) or not opt.strip():
                raise ValueError("options must contain non-empty strings")

        if len(set(opts)) < 2:
            raise ValueError("options must contain at least two unique non-empty strings")

        object.__setattr__(self, "options", opts)

        if not isinstance(self.context, dict):
            raise ValueError("context must be a dict")
        object.__setattr__(self, "context", deepcopy(self.context))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "question": self.question,
            "options": list(self.options),
            "priority": self.priority.value,
            "blocking_task_id": self.blocking_task_id,
            "context": deepcopy(self.context),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionRequest":
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        required = {
            "decision_id",
            "question",
            "options",
            "priority",
            "blocking_task_id",
        }
        missing = required - payload.keys()
        if missing:
            raise ValueError(f"missing required keys: {sorted(missing)}")

        context = payload.get("context", {})
        if not isinstance(context, dict):
            raise ValueError("context must be a dict")

        return cls(
            decision_id=payload["decision_id"],
            question=payload["question"],
            options=tuple(payload["options"]) if isinstance(payload["options"], (list, tuple)) else payload["options"],
            priority=payload["priority"],
            blocking_task_id=payload["blocking_task_id"],
            context=deepcopy(context),
        )


@dataclass(frozen=True, slots=True)
class DecisionResponse:
    decision_id: str
    text: str
    selected_option: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision_id, str) or not self.decision_id.strip():
            raise ValueError("decision_id must be a non-empty string")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text must be a non-empty string")
        if self.selected_option is not None:
            if not isinstance(self.selected_option, str) or not self.selected_option.strip():
                raise ValueError("selected_option must be a non-empty string or None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "text": self.text,
            "selected_option": self.selected_option,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionResponse":
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        if "decision_id" not in payload or "text" not in payload:
            raise ValueError("payload must include decision_id and text")
        return cls(
            decision_id=payload["decision_id"],
            text=payload["text"],
            selected_option=payload.get("selected_option"),
        )


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    request: DecisionRequest
    status: DecisionStatus = DecisionStatus.OPEN
    response: DecisionResponse | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, DecisionRequest):
            raise ValueError("request must be a DecisionRequest")

        try:
            status_enum = DecisionStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid status: {self.status}") from exc
        object.__setattr__(self, "status", status_enum)

        if self.status is DecisionStatus.OPEN:
            if self.response is not None:
                raise ValueError("OPEN decision cannot have a response")
            return

        if self.status is DecisionStatus.CANCELLED:
            if self.response is not None:
                raise ValueError("CANCELLED decision cannot have a response")
            return

        if self.status is DecisionStatus.RESOLVED:
            if not isinstance(self.response, DecisionResponse):
                raise ValueError("RESOLVED decision requires a DecisionResponse")
            if self.response.decision_id != self.request.decision_id:
                raise ValueError("response decision_id does not match request decision_id")
            if (
                self.response.selected_option is not None
                and self.response.selected_option not in self.request.options
            ):
                raise ValueError("selected_option must be one of request.options")
            return

        raise ValueError(f"unhandled status: {self.status}")

    @property
    def decision_id(self) -> str:
        return self.request.decision_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "status": self.status.value,
            "response": self.response.to_dict() if self.response is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DecisionRecord":
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")
        if "request" not in payload or "status" not in payload:
            raise ValueError("payload must include request and status")

        request_payload = payload["request"]
        if not isinstance(request_payload, dict):
            raise ValueError("request must be a dict")

        response_payload = payload.get("response")
        if response_payload is not None and not isinstance(response_payload, dict):
            raise ValueError("response must be a dict or None")

        return cls(
            request=DecisionRequest.from_dict(deepcopy(request_payload)),
            status=payload["status"],
            response=(
                DecisionResponse.from_dict(deepcopy(response_payload))
                if response_payload is not None
                else None
            ),
        )
