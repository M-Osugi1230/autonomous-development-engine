from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ade import (
    DecisionKind,
    DecisionPriority,
    DecisionRequest,
    DecisionResponse,
    DecisionStatus,
    DecisionStore,
    HumanInterruptCoordinator,
    InterruptDisposition,
    InterruptPolicy,
)


class HumanInterruptCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = DecisionStore(Path(self.temp_dir.name) / "decisions.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def request(self, decision_id: str = "dec-1") -> DecisionRequest:
        return DecisionRequest(
            decision_id=decision_id,
            question="Proceed with the destructive operation?",
            options=("approve", "reject"),
            priority=DecisionPriority.P0,
            blocking_task_id="task-1",
            context={"scope": "database"},
        )

    def test_routine_reversible_proceeds_without_record(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        disposition = coordinator.request_decision(
            DecisionKind.ROUTINE_REVERSIBLE,
            self.request(),
        )

        self.assertEqual(disposition, InterruptDisposition.PROCEED)
        self.assertEqual(self.store.load(), ())

    def test_high_risk_request_queues_exactly_one_open_decision(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()

        for kind in (
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            DecisionKind.CREDENTIAL_OR_SECRET,
            DecisionKind.EXTERNAL_SIDE_EFFECT,
        ):
            isolated_store = DecisionStore(
                Path(self.temp_dir.name) / f"{kind.value}.json"
            )
            isolated = HumanInterruptCoordinator(isolated_store)
            disposition = isolated.request_decision(kind, request)
            self.assertEqual(disposition, InterruptDisposition.HUMAN_WAIT)
            open_records = isolated_store.list_open()
            self.assertEqual(len(open_records), 1)
            self.assertEqual(open_records[0].status, DecisionStatus.OPEN)
            self.assertEqual(open_records[0].request, request)

    def test_repeated_open_request_is_idempotent(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()

        first = coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )
        second = coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )

        self.assertEqual(first, InterruptDisposition.HUMAN_WAIT)
        self.assertEqual(second, InterruptDisposition.HUMAN_WAIT)
        self.assertEqual(len(self.store.load()), 1)

    def test_existing_open_decision_cannot_be_bypassed_by_policy_change(self) -> None:
        request = DecisionRequest(
            decision_id="pref-1",
            question="Choose a presentation style?",
            options=("compact", "detailed"),
            priority=DecisionPriority.P2,
            blocking_task_id="task-2",
        )

        waiting = HumanInterruptCoordinator(self.store)
        self.assertEqual(
            waiting.request_decision(DecisionKind.USER_PREFERENCE, request),
            InterruptDisposition.HUMAN_WAIT,
        )

        permissive = HumanInterruptCoordinator(
            self.store,
            policy=InterruptPolicy(
                user_preference=InterruptDisposition.PROCEED,
            ),
        )
        self.assertEqual(
            permissive.request_decision(DecisionKind.USER_PREFERENCE, request),
            InterruptDisposition.HUMAN_WAIT,
        )
        self.assertEqual(len(self.store.load()), 1)

    def test_resolve_and_retrieve_response(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )

        response = DecisionResponse(
            decision_id=request.decision_id,
            text="Reject the operation until a backup is verified.",
            selected_option="reject",
        )
        record = coordinator.resolve(request.decision_id, response)

        self.assertEqual(record.status, DecisionStatus.RESOLVED)
        self.assertEqual(coordinator.get_resolved_response(request.decision_id), response)
        self.assertEqual(self.store.list_open(), ())

    def test_conflicting_or_repeated_resolution_is_rejected(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )
        response = DecisionResponse(
            decision_id=request.decision_id,
            text="Approved.",
            selected_option="approve",
        )
        coordinator.resolve(request.decision_id, response)

        with self.assertRaises(ValueError):
            coordinator.resolve(request.decision_id, response)

        with self.assertRaises(ValueError):
            coordinator.resolve(
                request.decision_id,
                DecisionResponse(
                    decision_id=request.decision_id,
                    text="Rejected.",
                    selected_option="reject",
                ),
            )

    def test_response_id_must_match_requested_decision(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )

        with self.assertRaises(ValueError):
            coordinator.resolve(
                request.decision_id,
                DecisionResponse(
                    decision_id="different",
                    text="Approved.",
                    selected_option="approve",
                ),
            )

    def test_resolved_request_must_be_consumed_explicitly(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        request = self.request()
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )
        response = DecisionResponse(
            decision_id=request.decision_id,
            text="Approved.",
            selected_option="approve",
        )
        coordinator.resolve(request.decision_id, response)

        with self.assertRaises(ValueError):
            coordinator.request_decision(
                DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
                request,
            )
        self.assertEqual(coordinator.get_resolved_response(request.decision_id), response)

    def test_decision_id_conflict_is_rejected(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        original = self.request("same-id")
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            original,
        )

        conflicting = DecisionRequest(
            decision_id="same-id",
            question="Different question?",
            options=("yes", "no"),
            priority=DecisionPriority.P1,
            blocking_task_id="task-other",
        )
        with self.assertRaises(ValueError):
            coordinator.request_decision(
                DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
                conflicting,
            )

    def test_policy_override_can_proceed_for_user_owned_soft_choice(self) -> None:
        policy = InterruptPolicy(
            specification_ambiguity=InterruptDisposition.PROCEED,
            user_preference=InterruptDisposition.PROCEED,
        )
        coordinator = HumanInterruptCoordinator(self.store, policy=policy)

        disposition = coordinator.request_decision(
            DecisionKind.USER_PREFERENCE,
            self.request("pref-proceed"),
        )

        self.assertEqual(disposition, InterruptDisposition.PROCEED)
        self.assertEqual(self.store.load(), ())

    def test_unknown_or_open_response_lookup_returns_none(self) -> None:
        coordinator = HumanInterruptCoordinator(self.store)
        self.assertIsNone(coordinator.get_resolved_response("missing"))

        request = self.request()
        coordinator.request_decision(
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            request,
        )
        self.assertIsNone(coordinator.get_resolved_response(request.decision_id))


if __name__ == "__main__":
    unittest.main()
