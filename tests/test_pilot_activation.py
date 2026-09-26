from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ade import (
    PilotAcceptanceCheck,
    PilotAction,
    PilotActivation,
    PilotActivationStore,
    PilotContract,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
    build_pilot_activation,
    pilot_contract_fingerprint,
    pilot_target_writes_allowed,
    require_pilot_target_write_activation,
)


def contract(*, require_human_activation: bool = True) -> PilotContract:
    return PilotContract(
        pilot_id="pilot-001",
        target=PilotTarget(
            repository="owner/repo",
            base_branch="main",
            baseline_sha="a" * 40,
        ),
        goal="Apply one bounded production change.",
        safety=PilotSafetyEnvelope(
            allowed_path_prefixes=("src", "tests"),
            forbidden_path_prefixes=(".github", ".autodev"),
            allowed_actions=(
                PilotAction.READ,
                PilotAction.CREATE_BRANCH,
                PilotAction.MODIFY_FILES,
                PilotAction.RUN_VALIDATION,
                PilotAction.OPEN_PULL_REQUEST,
            ),
            require_human_activation=require_human_activation,
        ),
        provider_policy=PilotProviderPolicy(
            allowed_provider_ids=("jules", "github-copilot"),
            preferred_provider_ids=("jules",),
        ),
        acceptance_checks=(
            PilotAcceptanceCheck(
                check_id="unit-tests",
                command="python -m unittest",
                timeout_seconds=120,
            ),
        ),
    )


class PilotActivationTests(unittest.TestCase):
    def test_contract_fingerprint_is_deterministic_and_contract_bound(self) -> None:
        original = contract()
        self.assertEqual(
            pilot_contract_fingerprint(original),
            pilot_contract_fingerprint(original),
        )

        changed = replace(original, goal="Apply a different bounded production change.")
        self.assertNotEqual(
            pilot_contract_fingerprint(original),
            pilot_contract_fingerprint(changed),
        )

    def test_matching_activation_allows_target_writes(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human@example",
            activated_at="2026-09-26T22:45:00+09:00",
        )

        self.assertTrue(pilot_target_writes_allowed(current, activation))
        require_pilot_target_write_activation(current, activation)
        self.assertEqual(activation.activated_at, "2026-09-26T13:45:00Z")

    def test_missing_activation_blocks_required_target_writes(self) -> None:
        current = contract()

        self.assertFalse(pilot_target_writes_allowed(current, None))
        with self.assertRaises(PermissionError):
            require_pilot_target_write_activation(current, None)

    def test_stale_activation_is_invalidated_by_contract_change(self) -> None:
        original = contract()
        activation = build_pilot_activation(
            original,
            activated_by="human",
            activated_at="2026-09-26T13:45:00Z",
        )
        changed = replace(original, goal="Changed after human activation.")

        self.assertFalse(pilot_target_writes_allowed(changed, activation))
        with self.assertRaises(PermissionError):
            require_pilot_target_write_activation(changed, activation)

    def test_activation_for_another_pilot_is_rejected(self) -> None:
        current = contract()
        activation = PilotActivation(
            pilot_id="pilot-002",
            contract_fingerprint=pilot_contract_fingerprint(current),
            activated_by="human",
            activated_at="2026-09-26T13:45:00Z",
        )

        self.assertFalse(pilot_target_writes_allowed(current, activation))

    def test_optional_activation_contract_allows_writes_without_record(self) -> None:
        current = contract(require_human_activation=False)

        self.assertTrue(pilot_target_writes_allowed(current, None))
        require_pilot_target_write_activation(current, None)

    def test_store_round_trip_and_write_gate(self) -> None:
        current = contract()
        activation = build_pilot_activation(
            current,
            activated_by="human",
            activated_at="2026-09-26T13:45:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activation.json"
            store = PilotActivationStore(path)

            self.assertIsNone(store.load())
            self.assertFalse(store.target_writes_allowed(current))
            with self.assertRaises(PermissionError):
                store.require_target_write_activation(current)

            store.save(activation)
            self.assertEqual(store.load(), activation)
            self.assertTrue(store.target_writes_allowed(current))
            store.require_target_write_activation(current)

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload, activation.to_dict())

    def test_store_rejects_invalid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activation.json"
            path.write_text('{"schema_version": 1}', encoding="utf-8")

            with self.assertRaises(ValueError):
                PilotActivationStore(path).load()


if __name__ == "__main__":
    unittest.main()
