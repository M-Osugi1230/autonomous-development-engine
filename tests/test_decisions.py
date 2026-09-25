from dataclasses import FrozenInstanceError
import unittest

from ade.decisions import DecisionPriority, DecisionRequest


class DecisionModelTests(unittest.TestCase):
    def test_decision_priority_enum_values(self):
        self.assertEqual(DecisionPriority.P0, "P0")
        self.assertEqual(DecisionPriority.P1, "P1")
        self.assertEqual(DecisionPriority.P2, "P2")
        self.assertEqual(DecisionPriority.P3, "P3")
        self.assertEqual(list(DecisionPriority), ["P0", "P1", "P2", "P3"])

    def test_decision_request_valid_creation(self):
        request = DecisionRequest(
            decision_id="dec-1",
            question="Which database backend should be used?",
            options=("postgres", "sqlite"),
            priority=DecisionPriority.P0,
            blocking_task_id="task-42",
            context={"env": "prod"},
        )
        self.assertEqual(request.decision_id, "dec-1")
        self.assertEqual(request.question, "Which database backend should be used?")
        self.assertEqual(request.options, ("postgres", "sqlite"))
        self.assertEqual(request.priority, DecisionPriority.P0)
        self.assertIsInstance(request.priority, DecisionPriority)
        self.assertEqual(request.blocking_task_id, "task-42")
        self.assertEqual(request.context, {"env": "prod"})

    def test_decision_request_string_priority_and_list_options(self):
        request = DecisionRequest(
            decision_id="dec-2",
            question="Proceed with deployment?",
            options=["yes", "no"],
            priority="P1",  # Passed as string
            blocking_task_id="task-99",
        )
        self.assertEqual(request.priority, DecisionPriority.P1)
        self.assertIsInstance(request.priority, DecisionPriority)
        self.assertEqual(request.options, ("yes", "no"))
        self.assertEqual(request.context, {})

    def test_decision_request_immutability(self):
        request = DecisionRequest(
            decision_id="dec-3",
            question="Approve hotfix?",
            options=("approve", "reject"),
            priority=DecisionPriority.P2,
            blocking_task_id="task-100",
        )
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            request.decision_id = "dec-4"  # type: ignore[misc]

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            request.priority = DecisionPriority.P3  # type: ignore[misc]

    def test_decision_request_validation_decision_id(self):
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="",
                question="Q?",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="   ",
                question="Q?",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

    def test_decision_request_validation_question(self):
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="  \t \n ",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

    def test_decision_request_validation_blocking_task_id(self):
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="",
            )
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="   ",
            )

    def test_decision_request_validation_priority(self):
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "b"),
                priority="P4",  # type: ignore[arg-type]
                blocking_task_id="t1",
            )

    def test_decision_request_validation_options(self):
        # Fewer than 2 options
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=(),  # type: ignore[arg-type]
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a",),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

        # Duplicate options (fewer than 2 unique options)
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "a"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

        # Contains empty or whitespace strings
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", ""),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "   "),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

        # Non-string element
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", 123),  # type: ignore[arg-type]
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
            )

    def test_decision_request_validation_context(self):
        with self.assertRaises(ValueError):
            DecisionRequest(
                decision_id="d1",
                question="Q?",
                options=("a", "b"),
                priority=DecisionPriority.P1,
                blocking_task_id="t1",
                context="invalid",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
