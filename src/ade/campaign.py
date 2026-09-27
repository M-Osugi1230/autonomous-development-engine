from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

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
