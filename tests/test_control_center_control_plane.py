from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


control_command = _load_module(
    "ade_trusted_control_command_test",
    ROOT / ".github" / "trusted" / "control_command.py",
)
control_api = _load_module("ade_control_api_test", ROOT / "api" / "control.py")
status_api = _load_module("ade_status_api_test", ROOT / "api" / "status.py")


class TrustedControlCommandTests(unittest.TestCase):
    def test_project_policy_is_exact_and_conservative(self) -> None:
        self.assertEqual(set(control_command.PROJECTS), {"jquants", "chu-kei", "jichi"})
        self.assertEqual(
            control_command.PROJECTS["chu-kei"].allowed_path_prefixes,
            ("operations/plan-detection/candidates",),
        )
        self.assertEqual(
            control_command.PROJECTS["jichi"].allowed_path_prefixes,
            ("data/candidates", "tests"),
        )
        self.assertNotIn("data/reviewed", control_command.PROJECTS["jichi"].allowed_path_prefixes)

    def test_unknown_command_and_cross_project_all_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            control_command.run_command("jquants", "delete", {})
        with self.assertRaises(ValueError):
            control_command.run_command("all", "resume", {})

    def test_goal_build_uses_controller_owned_scope(self) -> None:
        policy = control_command.PROJECTS["jquants"]
        with patch.object(control_command, "_project_is_idle", return_value=True):
            payload = control_command._build_goal(
                policy,
                {"goal": "Add a bounded, tested research improvement without expanding data categories."},
            )
        self.assertEqual(payload["target_repository"], policy.target_repository)
        self.assertEqual(tuple(payload["allowed_path_prefixes"]), policy.allowed_path_prefixes)
        self.assertEqual(payload["base_branch"], "main")
        self.assertEqual(payload["execution_phase"], "autonomous-development")

    def test_active_project_rejects_goal_replacement(self) -> None:
        policy = control_command.PROJECTS["jquants"]
        with patch.object(control_command, "_project_is_idle", return_value=False):
            with self.assertRaisesRegex(ValueError, "active task"):
                control_command._build_goal(
                    policy,
                    {"goal": "Attempt to replace an active campaign from the web Control Center."},
                )

    def test_goal_rejects_extra_authority_fields(self) -> None:
        policy = control_command.PROJECTS["jichi"]
        with patch.object(control_command, "_project_is_idle", return_value=True):
            with self.assertRaisesRegex(ValueError, "unsupported fields"):
                control_command._build_goal(
                    policy,
                    {
                        "goal": "Prepare the next bounded municipality candidate with tests and primary-source evidence.",
                        "allowed_path_prefixes": ["data/reviewed"],
                    },
                )


class ControlApiTests(unittest.TestCase):
    def test_request_contract_is_small_and_explicit(self) -> None:
        project, command, payload = control_api._validate_request(
            {"project": "jquants", "command": "resume", "payload": {}}
        )
        self.assertEqual((project, command, payload), ("jquants", "resume", {}))
        with self.assertRaises(ValueError):
            control_api._validate_request(
                {"project": "all", "command": "resume", "payload": {}}
            )
        with self.assertRaises(ValueError):
            control_api._validate_request(
                {"project": "jquants", "command": "resume", "payload": {}, "token": "x"}
            )

    def test_control_api_uses_only_server_side_github_credential(self) -> None:
        with patch.dict(os.environ, {"ADE_GITHUB_TOKEN": "server-only-token"}, clear=False):
            self.assertEqual(control_api._github_token(), "server-only-token")
        self.assertFalse(hasattr(control_api, "_authorized"))
        self.assertFalse(hasattr(control_api, "_configured_key"))


class StatusApiTests(unittest.TestCase):
    def test_open_decisions_expose_only_operator_fields(self) -> None:
        payload = {
            "decisions": [
                {
                    "status": "OPEN",
                    "request": {
                        "decision_id": "d-1",
                        "question": "Approve bounded action?",
                        "priority": "P0",
                        "blocking_task_id": "task-1",
                        "options": ["approve", "reject"],
                        "context": {"secret_internal_detail": "must-not-leak"},
                    },
                }
            ]
        }
        decisions = status_api._open_decisions(payload)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            set(decisions[0]),
            {"decision_id", "question", "priority", "blocking_task_id", "options"},
        )
        self.assertNotIn("context", json.dumps(decisions))


if __name__ == "__main__":
    unittest.main()
