from __future__ import annotations

import unittest

from ade import (
    DecisionKind,
    InterruptDisposition,
    InterruptPolicy,
    decide_interrupt,
)


class InterruptPolicyTests(unittest.TestCase):
    def test_default_policy_covers_every_decision_kind(self) -> None:
        policy = InterruptPolicy()

        expected = {
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE: InterruptDisposition.HUMAN_WAIT,
            DecisionKind.CREDENTIAL_OR_SECRET: InterruptDisposition.HUMAN_WAIT,
            DecisionKind.EXTERNAL_SIDE_EFFECT: InterruptDisposition.HUMAN_WAIT,
            DecisionKind.SPECIFICATION_AMBIGUITY: InterruptDisposition.HUMAN_WAIT,
            DecisionKind.USER_PREFERENCE: InterruptDisposition.HUMAN_WAIT,
            DecisionKind.ROUTINE_REVERSIBLE: InterruptDisposition.PROCEED,
        }

        self.assertEqual(
            {kind: policy.decide(kind) for kind in DecisionKind},
            expected,
        )

    def test_high_risk_kinds_are_fixed_to_human_wait(self) -> None:
        policy = InterruptPolicy(
            specification_ambiguity=InterruptDisposition.PROCEED,
            user_preference=InterruptDisposition.PROCEED,
        )

        for kind in (
            DecisionKind.DESTRUCTIVE_OR_IRREVERSIBLE,
            DecisionKind.CREDENTIAL_OR_SECRET,
            DecisionKind.EXTERNAL_SIDE_EFFECT,
        ):
            self.assertEqual(
                policy.decide(kind),
                InterruptDisposition.HUMAN_WAIT,
            )

    def test_routine_reversible_is_fixed_to_proceed(self) -> None:
        policy = InterruptPolicy(
            specification_ambiguity=InterruptDisposition.HUMAN_WAIT,
            user_preference=InterruptDisposition.HUMAN_WAIT,
        )
        self.assertEqual(
            policy.decide(DecisionKind.ROUTINE_REVERSIBLE),
            InterruptDisposition.PROCEED,
        )

    def test_configurable_ambiguity_and_preference_overrides(self) -> None:
        policy = InterruptPolicy(
            specification_ambiguity="PROCEED",
            user_preference="PROCEED",
        )

        self.assertEqual(
            policy.decide(DecisionKind.SPECIFICATION_AMBIGUITY),
            InterruptDisposition.PROCEED,
        )
        self.assertEqual(
            policy.decide(DecisionKind.USER_PREFERENCE),
            InterruptDisposition.PROCEED,
        )

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InterruptPolicy(specification_ambiguity="MAYBE")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            InterruptPolicy(user_preference="MAYBE")  # type: ignore[arg-type]

    def test_invalid_decision_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            InterruptPolicy().decide("unknown-kind")

    def test_top_level_helper_uses_default_or_explicit_policy(self) -> None:
        self.assertEqual(
            decide_interrupt(DecisionKind.ROUTINE_REVERSIBLE),
            InterruptDisposition.PROCEED,
        )
        self.assertEqual(
            decide_interrupt(
                DecisionKind.USER_PREFERENCE,
                policy=InterruptPolicy(user_preference=InterruptDisposition.PROCEED),
            ),
            InterruptDisposition.PROCEED,
        )
        with self.assertRaises(ValueError):
            decide_interrupt(
                DecisionKind.USER_PREFERENCE,
                policy="invalid",  # type: ignore[arg-type]
            )

    def test_repeated_decisions_are_deterministic(self) -> None:
        policy = InterruptPolicy(
            specification_ambiguity=InterruptDisposition.PROCEED,
            user_preference=InterruptDisposition.HUMAN_WAIT,
        )

        first = [policy.decide(kind) for kind in DecisionKind]
        for _ in range(20):
            self.assertEqual(
                [policy.decide(kind) for kind in DecisionKind],
                first,
            )


if __name__ == "__main__":
    unittest.main()
