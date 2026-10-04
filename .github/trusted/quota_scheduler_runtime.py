from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ade.quota_scheduler import (
    GlobalQuotaPolicy,
    QuotaAdmissionDecision,
    evaluate_quota_admission,
    tagged_session_title,
)

POLICY_PATH = Path(".autodev/global-quota-policy.json")
EVIDENCE_PATH = ".autodev/runtime/quota-admission.json"


class JulesSessionLister(Protocol):
    def list_sessions(
        self,
        *,
        page_size: int = 100,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        ...


class ControllerReader(Protocol):
    def get_json_file(
        self,
        path: str,
        *,
        ref: str = "main",
    ) -> tuple[dict[str, Any], str]:
        ...

    def upsert_json_file(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        message: str,
        branch: str = "main",
    ) -> None:
        ...


def _load_policy() -> GlobalQuotaPolicy:
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("global quota policy must be a JSON object")
    policy = GlobalQuotaPolicy.from_dict(payload)
    raw_limit = os.environ.get("ADE_JULES_DAILY_TASK_LIMIT")
    if raw_limit is None:
        return policy
    try:
        daily_limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("ADE_JULES_DAILY_TASK_LIMIT must be an integer") from exc
    return GlobalQuotaPolicy(
        daily_limit=daily_limit,
        rolling_window_hours=policy.rolling_window_hours,
        grace_minutes=policy.grace_minutes,
        projects=policy.projects,
    )


def _read_optional(
    gh: ControllerReader,
    path: str,
    *,
    ref: str,
) -> dict[str, Any] | None:
    try:
        payload, _ = gh.get_json_file(path, ref=ref)
        return payload
    except Exception as exc:
        if "404" in str(exc):
            return None
        raise


def _project_has_demand(
    gh: ControllerReader,
    *,
    project_key: str,
) -> bool:
    state = _read_optional(gh, ".autodev/state.json", ref=project_key)
    planning = _read_optional(
        gh,
        ".autodev/runtime/planning-status.json",
        ref=project_key,
    )
    goal = _read_optional(gh, ".autodev/planning-goal.json", ref=project_key)

    if state is not None:
        status = state.get("status")
        current_task_id = state.get("current_task_id")
        if (
            isinstance(current_task_id, str)
            and current_task_id
            and status in {"READY", "RUNNING", "PAUSED_QUOTA"}
        ):
            return True

    if goal is not None:
        goal_request = goal.get("request_id")
        planning_request = planning.get("request_id") if planning else None
        if (
            isinstance(goal_request, str)
            and goal_request
            and goal_request != planning_request
        ):
            return True

    if planning is not None and planning.get("state") in {
        "PAUSED_QUOTA",
        "REPLAN",
    }:
        return True

    return False


def active_project_keys(
    gh: ControllerReader,
    *,
    policy: GlobalQuotaPolicy,
    current_project_key: str,
) -> tuple[str, ...]:
    active: set[str] = {current_project_key}
    for project in policy.projects:
        if project.project_key == current_project_key:
            continue
        try:
            if _project_has_demand(gh, project_key=project.project_key):
                active.add(project.project_key)
        except Exception:
            # Preserve fairness when another controller branch is temporarily
            # unreadable. Treat it as active rather than allowing quota theft.
            active.add(project.project_key)
    return tuple(sorted(active))


def assess_jules_admission(
    *,
    client: JulesSessionLister,
    gh: ControllerReader,
    purpose: str,
    now: datetime | None = None,
) -> QuotaAdmissionDecision:
    if purpose not in {"planner", "implementation"}:
        raise ValueError("purpose must be planner or implementation")
    project_key = (
        os.environ.get("ADE_PROJECT_KEY")
        or os.environ.get("ADE_CONTROL_REF")
        or "main"
    ).strip()
    policy = _load_policy()
    active = active_project_keys(
        gh,
        policy=policy,
        current_project_key=project_key,
    )
    sessions = client.list_sessions(page_size=100, max_pages=10)
    decision = evaluate_quota_admission(
        policy=policy,
        project_key=project_key,
        sessions=sessions,
        active_project_keys=active,
        now=now or datetime.now(UTC),
    )
    payload = {
        **decision.to_dict(),
        "purpose": purpose,
        "observed_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
    }
    gh.upsert_json_file(
        EVIDENCE_PATH,
        payload,
        message=f"quota: {project_key} {purpose} {decision.reason}",
    )
    return decision


def tagged_title(title: str, *, purpose: str) -> str:
    project_key = (
        os.environ.get("ADE_PROJECT_KEY")
        or os.environ.get("ADE_CONTROL_REF")
        or "main"
    ).strip()
    return tagged_session_title(project_key, purpose, title)
