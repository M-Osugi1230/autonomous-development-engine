from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from ade.quota_scheduler import (
    GlobalQuotaPolicy,
    ProjectQuotaShare,
    evaluate_quota_admission,
    tagged_session_title,
)


def run_probe() -> dict[str, object]:
    now = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
    policy = GlobalQuotaPolicy(
        daily_limit=15,
        projects=(
            ProjectQuotaShare("ade-jquants", 6, 40),
            ProjectQuotaShare("ade-chu-kei", 5, 35),
            ProjectQuotaShare("ade-jichi-insight", 4, 25),
        ),
    )
    sessions: list[dict[str, object]] = []
    for index in range(6):
        sessions.append(
            {
                "createTime": (now - timedelta(hours=1, minutes=index)).isoformat(),
                "title": tagged_session_title(
                    "ade-jquants",
                    "implementation",
                    f"jq-{index}",
                ),
            }
        )
    sessions.append(
        {
            "createTime": (now - timedelta(hours=2)).isoformat(),
            "title": tagged_session_title(
                "ade-chu-kei",
                "implementation",
                "ck-1",
            ),
        }
    )

    protected = evaluate_quota_admission(
        policy=policy,
        project_key="ade-jquants",
        sessions=sessions,
        active_project_keys=("ade-jquants", "ade-chu-kei"),
        now=now,
    )
    if protected.allowed:
        raise AssertionError("scheduler allowed quota borrowing across active project reserve")
    if protected.reason != "project-soft-allocation-protected":
        raise AssertionError("scheduler returned unexpected protection reason")

    borrow = evaluate_quota_admission(
        policy=policy,
        project_key="ade-jquants",
        sessions=sessions,
        active_project_keys=("ade-jquants",),
        now=now,
    )
    if not borrow.allowed or borrow.reason != "borrowed-unused-allocation":
        raise AssertionError("scheduler did not allow safe borrowing from inactive projects")

    return {
        "ok": True,
        "protected_active_share": protected.reason,
        "borrowed_inactive_share": borrow.reason,
        "daily_limit": policy.daily_limit,
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
