from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_cycle_module():
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        path = TRUSTED_DIR / "jules_cycle.py"
        spec = importlib.util.spec_from_file_location("trusted_jules_cycle_quota_test", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to load trusted jules_cycle.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class FakeClient:
    def __init__(self, sessions):
        self.sessions = sessions

    def list_sessions(self, *, page_size=100, max_pages=10):
        return list(self.sessions)


class TrustedQuotaInferenceTests(unittest.TestCase):
    def test_below_limit_is_not_classified_as_quota(self) -> None:
        module = load_cycle_module()
        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
        sessions = [
            {"createTime": (now - timedelta(hours=23) + timedelta(minutes=i)).isoformat()}
            for i in range(14)
        ]
        self.assertIsNone(
            module._infer_rolling_quota_resume_after(
                FakeClient(sessions),
                now=now,
                daily_limit=15,
            )
        )

    def test_at_limit_uses_oldest_session_release_time(self) -> None:
        module = load_cycle_module()
        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
        oldest = now - timedelta(hours=23)
        sessions = [
            {"createTime": (oldest + timedelta(minutes=i)).isoformat()}
            for i in range(15)
        ]
        resume = module._infer_rolling_quota_resume_after(
            FakeClient(sessions),
            now=now,
            daily_limit=15,
        )
        self.assertEqual(resume, oldest + timedelta(hours=24, minutes=2))

    def test_over_limit_waits_until_enough_old_sessions_expire(self) -> None:
        module = load_cycle_module()
        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
        oldest = now - timedelta(hours=23)
        sessions = [
            {"createTime": (oldest + timedelta(minutes=i)).isoformat()}
            for i in range(16)
        ]
        resume = module._infer_rolling_quota_resume_after(
            FakeClient(sessions),
            now=now,
            daily_limit=15,
        )
        self.assertEqual(
            resume,
            oldest + timedelta(minutes=1) + timedelta(hours=24, minutes=2),
        )

    def test_invalid_or_old_session_timestamps_are_ignored(self) -> None:
        module = load_cycle_module()
        now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
        sessions = [
            {"createTime": "invalid"},
            {"createTime": (now - timedelta(hours=25)).isoformat()},
        ]
        self.assertIsNone(
            module._infer_rolling_quota_resume_after(
                FakeClient(sessions),
                now=now,
                daily_limit=1,
            )
        )


if __name__ == "__main__":
    unittest.main()
