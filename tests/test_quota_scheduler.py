from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from ade.quota_scheduler import (
    GlobalQuotaPolicy,
    ProjectQuotaShare,
    evaluate_quota_admission,
    tagged_session_title,
)


NOW = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)


def session(
    hours_ago: float,
    *,
    project_key: str | None = None,
    purpose: str = "implementation",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "createTime": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }
    if project_key is not None:
        payload["title"] = tagged_session_title(
            project_key,
            purpose,
            f"task-{hours_ago}",
        )
    else:
        payload["title"] = "unmanaged Jules task"
    return payload


class QuotaSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = GlobalQuotaPolicy(
            daily_limit=15,
            projects=(
                ProjectQuotaShare("ade-jquants", 6, 40),
                ProjectQuotaShare("ade-chu-kei", 5, 35),
                ProjectQuotaShare("ade-jichi-insight", 4, 25),
            ),
        )

    def test_allows_project_within_soft_allocation(self) -> None:
        decision = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jquants",
            sessions=[
                session(1, project_key="ade-jquants"),
                session(2, project_key="ade-chu-kei"),
            ],
            active_project_keys=(
                "ade-jquants",
                "ade-chu-kei",
                "ade-jichi-insight",
            ),
            now=NOW,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "within-soft-allocation")
        self.assertEqual(decision.project_used, 1)

    def test_blocks_when_global_limit_is_exhausted(self) -> None:
        sessions = [
            session(index / 2 + 0.5)
            for index in range(15)
        ]
        decision = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jquants",
            sessions=sessions,
            active_project_keys=("ade-jquants",),
            now=NOW,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "global-limit-exhausted")
        self.assertEqual(decision.remaining, 0)
        self.assertIsNotNone(decision.resume_after)

    def test_scarce_capacity_selects_lowest_fill_then_priority(self) -> None:
        sessions = []
        sessions.extend(
            session(1 + index / 10, project_key="ade-jquants")
            for index in range(5)
        )
        sessions.extend(
            session(2 + index / 10, project_key="ade-chu-kei")
            for index in range(4)
        )
        sessions.extend(
            session(3 + index / 10, project_key="ade-jichi-insight")
            for index in range(3)
        )
        sessions.extend(session(4 + index / 10) for index in range(2))
        # One slot remains. Fill ratios are JQ=5/6, Chu=4/5, Jichi=3/4;
        # Jichi has the lowest fill ratio and receives the scarce slot.
        jichi = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jichi-insight",
            sessions=sessions,
            active_project_keys=(
                "ade-jquants",
                "ade-chu-kei",
                "ade-jichi-insight",
            ),
            now=NOW,
        )
        jq = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jquants",
            sessions=sessions,
            active_project_keys=(
                "ade-jquants",
                "ade-chu-kei",
                "ade-jichi-insight",
            ),
            now=NOW,
        )
        self.assertTrue(jichi.allowed)
        self.assertEqual(
            jichi.reason,
            "scarce-capacity-selected-by-fair-share",
        )
        self.assertFalse(jq.allowed)
        self.assertEqual(
            jq.reason,
            "scarce-capacity-reserved-for-lower-fill-projects",
        )

    def test_project_at_share_cannot_borrow_from_active_competitor(self) -> None:
        sessions = [
            *[
                session(1 + index / 10, project_key="ade-jquants")
                for index in range(6)
            ],
            session(2, project_key="ade-chu-kei"),
        ]
        decision = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jquants",
            sessions=sessions,
            active_project_keys=("ade-jquants", "ade-chu-kei"),
            now=NOW,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            "project-soft-allocation-protected",
        )

    def test_project_can_borrow_when_competitors_are_inactive(self) -> None:
        sessions = [
            session(1 + index / 10, project_key="ade-jquants")
            for index in range(6)
        ]
        decision = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-jquants",
            sessions=sessions,
            active_project_keys=("ade-jquants",),
            now=NOW,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "borrowed-unused-allocation")

    def test_sessions_outside_rolling_window_do_not_count(self) -> None:
        decision = evaluate_quota_admission(
            policy=self.policy,
            project_key="ade-chu-kei",
            sessions=[
                session(25, project_key="ade-chu-kei"),
                session(1, project_key="ade-chu-kei"),
            ],
            active_project_keys=("ade-chu-kei",),
            now=NOW,
        )
        self.assertEqual(decision.total_used, 1)
        self.assertEqual(decision.project_used, 1)


if __name__ == "__main__":
    unittest.main()
