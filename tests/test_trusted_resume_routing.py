from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_trusted_module(filename: str, module_name: str):
    sys.path.insert(0, str(TRUSTED_DIR))
    try:
        path = TRUSTED_DIR / filename
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load {filename}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class TrustedResumeRoutingTests(unittest.TestCase):
    def test_due_quota_routes_without_local_state(self) -> None:
        module = load_trusted_module("jules_resume.py", "trusted_jules_resume_test")
        now = datetime(2026, 9, 26, 0, 30, tzinfo=UTC)

        action, session = module.decide_checkpoint_action(
            {
                "state": "PAUSED_QUOTA",
                "provider_session_id": None,
                "resume_after": (now - timedelta(minutes=1)).isoformat(),
            },
            now=now,
        )
        self.assertEqual((action, session), ("START_NEW", None))

        action, session = module.decide_checkpoint_action(
            {
                "state": "PAUSED_QUOTA",
                "provider_session_id": "sess-1",
                "resume_after": (now - timedelta(minutes=1)).isoformat(),
            },
            now=now,
        )
        self.assertEqual((action, session), ("MONITOR", "sess-1"))

    def test_future_quota_waits_and_human_wait_never_resumes(self) -> None:
        module = load_trusted_module("jules_resume.py", "trusted_jules_resume_test_2")
        now = datetime(2026, 9, 26, 0, 30, tzinfo=UTC)

        action, _ = module.decide_checkpoint_action(
            {
                "state": "PAUSED_QUOTA",
                "provider_session_id": "sess-1",
                "resume_after": (now + timedelta(minutes=1)).isoformat(),
            },
            now=now,
        )
        self.assertEqual(action, "WAIT")

        action, _ = module.decide_checkpoint_action(
            {
                "state": "HUMAN_WAIT",
                "provider_session_id": "sess-1",
                "resume_after": None,
            },
            now=now,
        )
        self.assertEqual(action, "NOOP")


    def test_external_target_is_preserved_for_quota_resume(self) -> None:
        module = load_trusted_module("jules_resume.py", "trusted_jules_resume_target_test")
        target = module.resolve_resume_target(
            {
                "metadata": {
                    "target_repository": "M-Osugi1230/one-minute-thought-experiments"
                }
            },
            controller_owner="M-Osugi1230",
            controller_repo="autonomous-development-engine",
        )
        self.assertEqual(
            target,
            "M-Osugi1230/one-minute-thought-experiments",
        )

        fallback = module.resolve_resume_target(
            {"metadata": {}},
            controller_owner="M-Osugi1230",
            controller_repo="autonomous-development-engine",
        )
        self.assertEqual(
            fallback,
            "M-Osugi1230/autonomous-development-engine",
        )

    def test_resume_uses_execution_lease_before_starting_new_session(self) -> None:
        source = (TRUSTED_DIR / "jules_resume.py").read_text(encoding="utf-8")
        self.assertIn("claim_execution(", source)
        self.assertIn("github-actions-resume:", source)
        self.assertLess(
            source.index("claim_execution("),
            source.index('print("RESUME: quota window elapsed; starting a new Jules session")'),
        )

    def test_cloud_probe_helper(self) -> None:
        module = load_trusted_module("resume_probe.py", "trusted_resume_probe_test")
        result = module.run_probe()
        self.assertTrue(result["ok"])
        self.assertEqual(result["due_without_session"], "START_NEW")
        self.assertEqual(result["due_with_session"], "MONITOR")
        self.assertEqual(result["not_due"], "WAIT")


if __name__ == "__main__":
    unittest.main()
