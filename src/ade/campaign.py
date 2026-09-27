from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from .checkpoint import SECRET_PATTERNS


class CampaignStatus(StrEnum):
    READY="READY"; RUNNING="RUNNING"; HUMAN_WAIT="HUMAN_WAIT"; FAILED="FAILED"; COMPLETED="COMPLETED"

@dataclass(frozen=True,slots=True)
class AutonomousCampaign:
    campaign_id:str; goal:str; task_ids:tuple[str,...]; status:CampaignStatus=CampaignStatus.READY; completed_task_ids:tuple[str,...]=()
    def __post_init__(self):
        if not isinstance(self.campaign_id,str) or not self.campaign_id.strip(): raise ValueError("campaign_id must be non-empty")
        if not isinstance(self.goal,str) or not self.goal.strip(): raise ValueError("goal must be non-empty")
        if not self.task_ids or len(set(self.task_ids))!=len(self.task_ids): raise ValueError("task_ids must be non-empty and unique")
        if any(not isinstance(x,str) or not x.strip() for x in self.task_ids): raise ValueError("task_ids must contain non-empty strings")
        if any(x not in self.task_ids for x in self.completed_task_ids): raise ValueError("completed task is not in campaign")
        object.__setattr__(self,"status",CampaignStatus(self.status))
    @property
    def progress(self)->tuple[int,int]: return len(self.completed_task_ids),len(self.task_ids)
    def to_dict(self)->dict[str,Any]: return {"schema_version":1,"campaign_id":self.campaign_id,"goal":self.goal,"task_ids":list(self.task_ids),"status":self.status.value,"completed_task_ids":list(self.completed_task_ids)}
    @classmethod
    def from_dict(cls,p:dict[str,Any])->"AutonomousCampaign":
        if p.get("schema_version")!=1: raise ValueError("campaign schema_version must be 1")
        return cls(p["campaign_id"],p["goal"],tuple(p["task_ids"]),p.get("status","READY"),tuple(p.get("completed_task_ids",[])))


def _validate_secret_free(text: str, field_name: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise ValueError(f"{field_name} contains a forbidden secret pattern")
    return text


@dataclass(frozen=True, slots=True)
class CampaignEvidenceSummary:
    campaign_id: str
    goal: str
    completed_task_count: int
    total_task_count: int
    terminal_status: str
    task_ids: tuple[str, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("campaign evidence summary schema_version must be 1")
        _validate_secret_free(self.campaign_id, "campaign_id")
        _validate_secret_free(self.goal, "goal")

        if type(self.completed_task_count) is not int or self.completed_task_count < 0:
            raise ValueError("completed_task_count must be a non-negative integer")
        if type(self.total_task_count) is not int or self.total_task_count < 1:
            raise ValueError("total_task_count must be a positive integer")
        if self.completed_task_count > self.total_task_count:
            raise ValueError("completed_task_count cannot exceed total_task_count")

        try:
            status_enum = CampaignStatus(self.terminal_status)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid terminal_status: {self.terminal_status}") from exc
        object.__setattr__(self, "terminal_status", status_enum.value)

        raw_tasks = self.task_ids
        if not isinstance(raw_tasks, tuple):
            try:
                raw_tasks = tuple(raw_tasks)
            except TypeError as exc:
                raise ValueError("task_ids must be iterable") from exc
        if not raw_tasks:
            raise ValueError("task_ids must not be empty")
        if len(raw_tasks) != self.total_task_count:
            raise ValueError("task_ids count must equal total_task_count")
        if len(set(raw_tasks)) != len(raw_tasks):
            raise ValueError("task_ids must not contain duplicates")
        for tid in raw_tasks:
            _validate_secret_free(tid, "task_ids entry")
        object.__setattr__(self, "task_ids", raw_tasks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "goal": self.goal,
            "completed_task_count": self.completed_task_count,
            "total_task_count": self.total_task_count,
            "terminal_status": self.terminal_status,
            "task_ids": list(self.task_ids),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CampaignEvidenceSummary:
        if not isinstance(payload, dict):
            raise ValueError("campaign evidence summary must be a JSON object")
        if payload.get("schema_version") != 1:
            raise ValueError("campaign evidence summary schema_version must be 1")
        task_ids = payload.get("task_ids")
        if not isinstance(task_ids, list):
            raise ValueError("task_ids must be a list")
        return cls(
            schema_version=payload.get("schema_version", 1),
            campaign_id=payload["campaign_id"],
            goal=payload["goal"],
            completed_task_count=payload["completed_task_count"],
            total_task_count=payload["total_task_count"],
            terminal_status=payload["terminal_status"],
            task_ids=tuple(task_ids),
        )


def summarize_campaign_evidence(campaign: AutonomousCampaign) -> CampaignEvidenceSummary:
    if not isinstance(campaign, AutonomousCampaign):
        raise TypeError(f"expected AutonomousCampaign, got {type(campaign).__name__}")
    completed_count, total_count = campaign.progress
    return CampaignEvidenceSummary(
        campaign_id=campaign.campaign_id,
        goal=campaign.goal,
        completed_task_count=completed_count,
        total_task_count=total_count,
        terminal_status=campaign.status.value,
        task_ids=campaign.task_ids,
    )
