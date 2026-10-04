from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any, Iterable

_TAG = re.compile(r"^\[ADE:([A-Za-z0-9._-]+):(planner|implementation)\]\s*")


@dataclass(frozen=True, slots=True)
class ProjectQuotaShare:
    project_key: str
    allocation: int
    priority: int = 100

    def __post_init__(self) -> None:
        if not isinstance(self.project_key, str) or not self.project_key.strip():
            raise ValueError("project_key must be a non-empty string")
        if self.project_key != self.project_key.strip():
            raise ValueError("project_key must not contain surrounding whitespace")
        if type(self.allocation) is not int or self.allocation < 1:
            raise ValueError("allocation must be a positive integer")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("priority must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class GlobalQuotaPolicy:
    daily_limit: int
    rolling_window_hours: int = 24
    grace_minutes: int = 2
    projects: tuple[ProjectQuotaShare, ...] = ()

    def __post_init__(self) -> None:
        if type(self.daily_limit) is not int or self.daily_limit < 1:
            raise ValueError("daily_limit must be a positive integer")
        if type(self.rolling_window_hours) is not int or self.rolling_window_hours < 1:
            raise ValueError("rolling_window_hours must be a positive integer")
        if type(self.grace_minutes) is not int or self.grace_minutes < 0:
            raise ValueError("grace_minutes must be a non-negative integer")
        seen: set[str] = set()
        for project in self.projects:
            if not isinstance(project, ProjectQuotaShare):
                raise ValueError("projects must contain ProjectQuotaShare values")
            if project.project_key in seen:
                raise ValueError(f"duplicate project_key: {project.project_key}")
            seen.add(project.project_key)
        if sum(project.allocation for project in self.projects) > self.daily_limit:
            raise ValueError("project allocations must not exceed daily_limit")

    def project(self, project_key: str) -> ProjectQuotaShare | None:
        for project in self.projects:
            if project.project_key == project_key:
                return project
        return None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GlobalQuotaPolicy":
        if not isinstance(payload, dict):
            raise ValueError("quota policy must be a JSON object")
        projects_raw = payload.get("projects", [])
        if not isinstance(projects_raw, list):
            raise ValueError("quota policy projects must be a list")
        projects: list[ProjectQuotaShare] = []
        for item in projects_raw:
            if not isinstance(item, dict):
                raise ValueError("quota policy project entries must be objects")
            projects.append(
                ProjectQuotaShare(
                    project_key=str(item.get("project_key", "")),
                    allocation=int(item.get("allocation", 0)),
                    priority=int(item.get("priority", 100)),
                )
            )
        return cls(
            daily_limit=int(payload.get("daily_limit", 0)),
            rolling_window_hours=int(payload.get("rolling_window_hours", 24)),
            grace_minutes=int(payload.get("grace_minutes", 2)),
            projects=tuple(projects),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "daily_limit": self.daily_limit,
            "rolling_window_hours": self.rolling_window_hours,
            "grace_minutes": self.grace_minutes,
            "projects": [
                {
                    "project_key": project.project_key,
                    "allocation": project.allocation,
                    "priority": project.priority,
                }
                for project in self.projects
            ],
        }


@dataclass(frozen=True, slots=True)
class SessionUsage:
    created_at: datetime
    project_key: str | None
    purpose: str | None


@dataclass(frozen=True, slots=True)
class QuotaAdmissionDecision:
    allowed: bool
    reason: str
    project_key: str
    daily_limit: int
    total_used: int
    remaining: int
    project_used: int
    project_allocation: int | None
    active_project_keys: tuple[str, ...]
    selected_project_keys: tuple[str, ...]
    unknown_session_count: int
    resume_after: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "allowed": self.allowed,
            "reason": self.reason,
            "project_key": self.project_key,
            "daily_limit": self.daily_limit,
            "total_used": self.total_used,
            "remaining": self.remaining,
            "project_used": self.project_used,
            "project_allocation": self.project_allocation,
            "active_project_keys": list(self.active_project_keys),
            "selected_project_keys": list(self.selected_project_keys),
            "unknown_session_count": self.unknown_session_count,
            "resume_after": self.resume_after,
        }


def tagged_session_title(project_key: str, purpose: str, title: str) -> str:
    if purpose not in {"planner", "implementation"}:
        raise ValueError("purpose must be planner or implementation")
    if not isinstance(project_key, str) or not project_key.strip():
        raise ValueError("project_key must be non-empty")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be non-empty")
    return f"[ADE:{project_key.strip()}:{purpose}] {title.strip()}"


def _session_time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _session_tag(session: dict[str, Any]) -> tuple[str | None, str | None]:
    title = session.get("title")
    if not isinstance(title, str):
        return None, None
    match = _TAG.match(title)
    if match is None:
        return None, None
    return match.group(1), match.group(2)


def collect_session_usage(
    sessions: Iterable[dict[str, Any]],
    *,
    now: datetime,
    rolling_window_hours: int,
) -> tuple[SessionUsage, ...]:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if type(rolling_window_hours) is not int or rolling_window_hours < 1:
        raise ValueError("rolling_window_hours must be positive")
    cutoff = now.astimezone(UTC) - timedelta(hours=rolling_window_hours)
    usage: list[SessionUsage] = []
    for session in sessions:
        if not isinstance(session, dict):
            continue
        created = (
            _session_time(session.get("createTime"))
            or _session_time(session.get("created_at"))
            or _session_time(session.get("createdAt"))
        )
        if created is None or created < cutoff:
            continue
        project_key, purpose = _session_tag(session)
        usage.append(
            SessionUsage(
                created_at=created,
                project_key=project_key,
                purpose=purpose,
            )
        )
    usage.sort(key=lambda item: item.created_at)
    return tuple(usage)


def _resume_after(
    usage: tuple[SessionUsage, ...],
    *,
    policy: GlobalQuotaPolicy,
    project_key: str | None = None,
) -> str | None:
    candidates = [
        item
        for item in usage
        if project_key is None or item.project_key == project_key
    ]
    if not candidates:
        candidates = list(usage)
    if not candidates:
        return None
    release = min(item.created_at for item in candidates)
    release += timedelta(
        hours=policy.rolling_window_hours,
        minutes=policy.grace_minutes,
    )
    return release.astimezone(UTC).isoformat()


def _fair_rank(
    project: ProjectQuotaShare,
    used: int,
) -> tuple[float, int, str]:
    fill_ratio = used / project.allocation
    return (fill_ratio, -project.priority, project.project_key)


def evaluate_quota_admission(
    *,
    policy: GlobalQuotaPolicy,
    project_key: str,
    sessions: Iterable[dict[str, Any]],
    active_project_keys: Iterable[str],
    now: datetime,
) -> QuotaAdmissionDecision:
    if not isinstance(project_key, str) or not project_key.strip():
        raise ValueError("project_key must be non-empty")
    project_key = project_key.strip()
    usage = collect_session_usage(
        sessions,
        now=now,
        rolling_window_hours=policy.rolling_window_hours,
    )
    total_used = len(usage)
    remaining = max(policy.daily_limit - total_used, 0)
    project_used = sum(1 for item in usage if item.project_key == project_key)
    unknown_count = sum(1 for item in usage if item.project_key is None)

    active = tuple(
        sorted(
            {
                key.strip()
                for key in active_project_keys
                if isinstance(key, str) and key.strip()
            }
            | {project_key}
        )
    )
    current_policy = policy.project(project_key)
    current_allocation = (
        current_policy.allocation if current_policy is not None else None
    )

    if remaining <= 0:
        return QuotaAdmissionDecision(
            allowed=False,
            reason="global-limit-exhausted",
            project_key=project_key,
            daily_limit=policy.daily_limit,
            total_used=total_used,
            remaining=remaining,
            project_used=project_used,
            project_allocation=current_allocation,
            active_project_keys=active,
            selected_project_keys=(),
            unknown_session_count=unknown_count,
            resume_after=_resume_after(usage, policy=policy),
        )

    if current_policy is None:
        return QuotaAdmissionDecision(
            allowed=True,
            reason="unmanaged-project-global-capacity-available",
            project_key=project_key,
            daily_limit=policy.daily_limit,
            total_used=total_used,
            remaining=remaining,
            project_used=project_used,
            project_allocation=None,
            active_project_keys=active,
            selected_project_keys=(project_key,),
            unknown_session_count=unknown_count,
            resume_after=None,
        )

    used_by_project = {
        project.project_key: sum(
            1 for item in usage if item.project_key == project.project_key
        )
        for project in policy.projects
    }
    under_share: list[ProjectQuotaShare] = [
        project
        for project in policy.projects
        if project.project_key in active
        and used_by_project[project.project_key] < project.allocation
    ]

    if project_used < current_policy.allocation:
        ranked = sorted(
            under_share,
            key=lambda project: _fair_rank(
                project,
                used_by_project[project.project_key],
            ),
        )
        if remaining < len(ranked):
            selected = tuple(
                project.project_key for project in ranked[:remaining]
            )
            if project_key not in selected:
                return QuotaAdmissionDecision(
                    allowed=False,
                    reason="scarce-capacity-reserved-for-lower-fill-projects",
                    project_key=project_key,
                    daily_limit=policy.daily_limit,
                    total_used=total_used,
                    remaining=remaining,
                    project_used=project_used,
                    project_allocation=current_policy.allocation,
                    active_project_keys=active,
                    selected_project_keys=selected,
                    unknown_session_count=unknown_count,
                    resume_after=_resume_after(usage, policy=policy),
                )
            reason = "scarce-capacity-selected-by-fair-share"
        else:
            selected = tuple(project.project_key for project in ranked)
            reason = "within-soft-allocation"
        return QuotaAdmissionDecision(
            allowed=True,
            reason=reason,
            project_key=project_key,
            daily_limit=policy.daily_limit,
            total_used=total_used,
            remaining=remaining,
            project_used=project_used,
            project_allocation=current_policy.allocation,
            active_project_keys=active,
            selected_project_keys=selected,
            unknown_session_count=unknown_count,
            resume_after=None,
        )

    protected = [
        project
        for project in under_share
        if project.project_key != project_key
    ]
    if protected:
        return QuotaAdmissionDecision(
            allowed=False,
            reason="project-soft-allocation-protected",
            project_key=project_key,
            daily_limit=policy.daily_limit,
            total_used=total_used,
            remaining=remaining,
            project_used=project_used,
            project_allocation=current_policy.allocation,
            active_project_keys=active,
            selected_project_keys=tuple(
                project.project_key
                for project in sorted(
                    protected,
                    key=lambda project: _fair_rank(
                        project,
                        used_by_project[project.project_key],
                    ),
                )
            ),
            unknown_session_count=unknown_count,
            resume_after=_resume_after(
                usage,
                policy=policy,
                project_key=project_key,
            ),
        )

    return QuotaAdmissionDecision(
        allowed=True,
        reason="borrowed-unused-allocation",
        project_key=project_key,
        daily_limit=policy.daily_limit,
        total_used=total_used,
        remaining=remaining,
        project_used=project_used,
        project_allocation=current_policy.allocation,
        active_project_keys=active,
        selected_project_keys=(project_key,),
        unknown_session_count=unknown_count,
        resume_after=None,
    )
