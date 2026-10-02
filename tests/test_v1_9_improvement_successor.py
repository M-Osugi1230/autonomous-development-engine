from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRUSTED = ROOT / ".github" / "trusted"


def load_module():
    trusted = str(TRUSTED)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED / "v1_9_improvement_successor.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_9_improvement_successor_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.9 improvement successor")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_json(relative: str):
    return json.loads(
        (ROOT / relative).read_text(encoding="utf-8")
    )


class V19ImprovementSuccessorTests(unittest.TestCase):
    def test_build_activation_is_tests_only_and_semantically_bound(self) -> None:
        module = load_module()
        state = load_json(".autodev/state.json")
        activation = module.build_activation(
            state_payload=state,
            source_release_payload=load_json(
                module.SOURCE_RELEASE_PATH
            ),
            source_finalization_payload=load_json(
                module.SOURCE_FINALIZATION_PATH
            ),
            source_target_payload=load_json(
                module.SOURCE_TARGET_PATH
            ),
        )

        self.assertEqual(
            activation["planning_goal"]["target_repository"],
            module.TARGET_REPOSITORY,
        )
        self.assertEqual(
            activation["planning_goal"]["allowed_path_prefixes"],
            ["tests"],
        )
        self.assertEqual(
            activation["planning_goal"]["max_tasks"],
            1,
        )
        self.assertIn(
            "U+2005 FOUR-PER-EM SPACE",
            activation["planning_goal"]["goal"],
        )
        self.assertIn(
            "U+2008 PUNCTUATION SPACE",
            activation["planning_goal"]["goal"],
        )
        self.assertEqual(
            activation["resolution"]["current_signal_ids"],
            [activation["actionable_signal_id"]],
        )
        self.assertEqual(
            activation["goal_receipt"]["status"],
            "HANDED_OFF",
        )
        self.assertEqual(
            activation["goal_receipt"]["handoff_count"],
            1,
        )
        self.assertEqual(
            activation["mission_control"]["cycle_state"],
            "HANDED_OFF",
        )
        self.assertEqual(
            activation["mission_control"]["current_count"],
            1,
        )

    def test_telemetry_observation_is_structured_and_behavior_preserving(self) -> None:
        module = load_module()
        payload = module._telemetry_observation()
        self.assertEqual(
            payload["observed_gap"]["test_path"],
            "tests/test_models.py",
        )
        self.assertEqual(
            payload["observed_gap"]["missing_codepoints"],
            [
                "U+2005 FOUR-PER-EM SPACE",
                "U+2008 PUNCTUATION SPACE",
            ],
        )
        self.assertFalse(
            payload["observed_gap"][
                "application_behavior_change_required"
            ]
        )
        serialized = json.dumps(payload, sort_keys=True)
        for forbidden in (
            "provider_session",
            "raw_provider",
            "credentials",
            "github_pat_",
            "ghp_",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_activation_requires_slice007_and_ready_state(self) -> None:
        module = load_module()
        state = load_json(".autodev/state.json")
        release = load_json(module.SOURCE_RELEASE_PATH)
        finalization = load_json(module.SOURCE_FINALIZATION_PATH)
        target = load_json(module.SOURCE_TARGET_PATH)

        missing = json.loads(json.dumps(state))
        missing["metadata"][
            "v1_9_slice_007_mission_control_observability"
        ] = False
        with self.assertRaisesRegex(
            ValueError,
            "Slice 007",
        ):
            module.build_activation(
                state_payload=missing,
                source_release_payload=release,
                source_finalization_payload=finalization,
                source_target_payload=target,
            )

        busy = json.loads(json.dumps(state))
        busy["status"] = "RUNNING"
        busy["current_task_id"] = "other-task"
        with self.assertRaisesRegex(
            ValueError,
            "READY",
        ):
            module.build_activation(
                state_payload=busy,
                source_release_payload=release,
                source_finalization_payload=finalization,
                source_target_payload=target,
            )


if __name__ == "__main__":
    unittest.main()
