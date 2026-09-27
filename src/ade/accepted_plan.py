from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .development_plan import DevelopmentPlan, PlannedTask

@dataclass(frozen=True, slots=True)
class AcceptedPlan:
    plan: DevelopmentPlan
    fingerprint: str
    status: str = "ACCEPTED"

    def __post_init__(self):
        if self.status not in {"ACCEPTED","RUNNING","COMPLETED","HUMAN_WAIT","FAILED"}:
            raise ValueError("invalid accepted plan status")
        expected=self.plan.fingerprint()
        if self.fingerprint != expected:
            raise ValueError("plan fingerprint mismatch")

    def to_dict(self)->dict[str,Any]:
        return {"schema_version":1,"status":self.status,"fingerprint":self.fingerprint,"plan":self.plan.canonical_dict()}

    @classmethod
    def accept(cls, plan:DevelopmentPlan)->"AcceptedPlan":
        plan.validate()
        return cls(plan,plan.fingerprint())

    @classmethod
    def from_dict(cls,payload:dict[str,Any])->"AcceptedPlan":
        if payload.get("schema_version")!=1: raise ValueError("accepted plan schema_version must be 1")
        raw=payload.get("plan")
        if not isinstance(raw,dict) or raw.get("schema_version")!=1: raise ValueError("accepted plan requires plan")
        tasks=tuple(PlannedTask(t["task_id"],t["title"],t["prompt"],tuple(t["depends_on"]),tuple(t["allowed_paths"]),tuple(t["acceptance"])) for t in raw["tasks"])
        plan=DevelopmentPlan(raw["goal"],tasks,tuple(raw.get("human_boundaries",[])))
        return cls(plan,str(payload["fingerprint"]),str(payload.get("status","ACCEPTED")))
