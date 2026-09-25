"""Autonomous Development Engine core package."""

from .acceptance import AcceptanceReport, CheckResult, build_report
from .decisions import DecisionPriority, DecisionRequest
from .health import health_snapshot
from .models import ProjectState, ProjectStatus, TaskStatus
from .repair import FailureKind, RepairDisposition, RepairPolicy, RepairState, decide_repair
from .repair_planner import RepairPlan, plan_repair
from .repair_runtime import RepairExecution, run_cycle_with_repair

__all__ = [
    "AcceptanceReport",
    "CheckResult",
    "DecisionPriority",
    "DecisionRequest",
    "FailureKind",
    "ProjectState",
    "ProjectStatus",
    "RepairDisposition",
    "RepairExecution",
    "RepairPlan",
    "RepairPolicy",
    "RepairState",
    "TaskStatus",
    "build_report",
    "decide_repair",
    "health_snapshot",
    "plan_repair",
    "run_cycle_with_repair",
]
