from dataclasses import FrozenInstanceError
import unittest

from ade.cycle import CycleFailed, CycleTimedOut, HumanInputRequired
from ade.providers.base import ProviderError, ProviderQuotaError, ProviderUnauthorizedError
from ade.repair import FailureKind, RepairDisposition, RepairPolicy, RepairState, classify_failure, decide_repair


class TestRepairPrimitives(unittest.TestCase):
    def test_enums(self) -> None:
        self.assertEqual(FailureKind.PROVIDER_QUOTA, "PROVIDER_QUOTA")
        self.assertEqual(FailureKind.HUMAN_INPUT, "HUMAN_INPUT")
        self.assertEqual(FailureKind.CYCLE_TIMEOUT, "CYCLE_TIMEOUT")
        self.assertEqual(FailureKind.CYCLE_FAILED, "CYCLE_FAILED")
        self.assertEqual(FailureKind.PROVIDER_ERROR, "PROVIDER_ERROR")
        self.assertEqual(FailureKind.VALIDATION_ERROR, "VALIDATION_ERROR")
        self.assertEqual(FailureKind.UNKNOWN, "UNKNOWN")

        self.assertEqual(RepairDisposition.RETRY, "RETRY")
        self.assertEqual(RepairDisposition.REPLAN, "REPLAN")
        self.assertEqual(RepairDisposition.PAUSE_QUOTA, "PAUSE_QUOTA")
        self.assertEqual(RepairDisposition.HUMAN_WAIT, "HUMAN_WAIT")
        self.assertEqual(RepairDisposition.FAIL, "FAIL")

    def test_repair_policy_defaults_and_custom(self) -> None:
        policy = RepairPolicy()
        self.assertEqual(policy.max_retries, 2)
        self.assertEqual(policy.max_replans, 1)

        custom_policy = RepairPolicy(max_retries=5, max_replans=3)
        self.assertEqual(custom_policy.max_retries, 5)
        self.assertEqual(custom_policy.max_replans, 3)

        zero_policy = RepairPolicy(max_retries=0, max_replans=0)
        self.assertEqual(zero_policy.max_retries, 0)
        self.assertEqual(zero_policy.max_replans, 0)

    def test_repair_policy_immutability(self) -> None:
        policy = RepairPolicy()
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            policy.max_retries = 10  # type: ignore[misc]

    def test_repair_policy_validation(self) -> None:
        invalid_values = [-1, "2", 2.5, True, False, None]
        for val in invalid_values:
            with self.assertRaises(ValueError):
                RepairPolicy(max_retries=val)  # type: ignore[arg-type]
            with self.assertRaises(ValueError):
                RepairPolicy(max_replans=val)  # type: ignore[arg-type]

    def test_repair_state_creation_and_immutability(self) -> None:
        state = RepairState(
            task_id="task-100",
            attempt=1,
            replan_count=0,
            last_failure_kind=FailureKind.CYCLE_TIMEOUT,
            last_error="Timeout after 300s",
        )
        self.assertEqual(state.task_id, "task-100")
        self.assertEqual(state.attempt, 1)
        self.assertEqual(state.replan_count, 0)
        self.assertEqual(state.last_failure_kind, FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(state.last_error, "Timeout after 300s")

        # Coercion from string failure kind
        state_str_kind = RepairState(
            task_id="task-101",
            attempt=0,
            replan_count=0,
            last_failure_kind="PROVIDER_QUOTA",  # type: ignore[arg-type]
        )
        self.assertEqual(state_str_kind.last_failure_kind, FailureKind.PROVIDER_QUOTA)
        self.assertIsNone(state_str_kind.last_error)

        with self.assertRaises((FrozenInstanceError, AttributeError)):
            state.attempt = 2  # type: ignore[misc]

    def test_repair_state_validation(self) -> None:
        # Invalid task_id
        for invalid_task_id in ["", "   ", 123, None]:
            with self.assertRaises(ValueError):
                RepairState(
                    task_id=invalid_task_id,  # type: ignore[arg-type]
                    attempt=0,
                    replan_count=0,
                    last_failure_kind=FailureKind.UNKNOWN,
                )

        # Invalid attempt
        for invalid_attempt in [-1, "0", 1.5, True, None]:
            with self.assertRaises(ValueError):
                RepairState(
                    task_id="t1",
                    attempt=invalid_attempt,  # type: ignore[arg-type]
                    replan_count=0,
                    last_failure_kind=FailureKind.UNKNOWN,
                )

        # Invalid replan_count
        for invalid_replan in [-1, "0", 1.5, True, None]:
            with self.assertRaises(ValueError):
                RepairState(
                    task_id="t1",
                    attempt=0,
                    replan_count=invalid_replan,  # type: ignore[arg-type]
                    last_failure_kind=FailureKind.UNKNOWN,
                )

        # Invalid last_failure_kind
        with self.assertRaises(ValueError):
            RepairState(
                task_id="t1",
                attempt=0,
                replan_count=0,
                last_failure_kind="INVALID_KIND",  # type: ignore[arg-type]
            )

        # Invalid last_error
        with self.assertRaises(ValueError):
            RepairState(
                task_id="t1",
                attempt=0,
                replan_count=0,
                last_failure_kind=FailureKind.UNKNOWN,
                last_error=12345,  # type: ignore[arg-type]
            )

    def test_decide_repair_provider_quota(self) -> None:
        self.assertEqual(
            decide_repair(FailureKind.PROVIDER_QUOTA, attempt=0, replan_count=0),
            RepairDisposition.PAUSE_QUOTA,
        )
        self.assertEqual(
            decide_repair("PROVIDER_QUOTA", attempt=10, replan_count=10),
            RepairDisposition.PAUSE_QUOTA,
        )

    def test_decide_repair_human_input(self) -> None:
        self.assertEqual(
            decide_repair(FailureKind.HUMAN_INPUT, attempt=0, replan_count=0),
            RepairDisposition.HUMAN_WAIT,
        )
        self.assertEqual(
            decide_repair("HUMAN_INPUT", attempt=5, replan_count=5),
            RepairDisposition.HUMAN_WAIT,
        )

    def test_decide_repair_retry_replan_fail_kinds(self) -> None:
        policy = RepairPolicy(max_retries=2, max_replans=1)
        retry_kinds = [
            FailureKind.CYCLE_TIMEOUT,
            FailureKind.CYCLE_FAILED,
            FailureKind.PROVIDER_ERROR,
            "CYCLE_TIMEOUT",
            "CYCLE_FAILED",
            "PROVIDER_ERROR",
        ]

        for kind in retry_kinds:
            # attempt < 2 -> RETRY
            self.assertEqual(
                decide_repair(kind, attempt=0, replan_count=0, policy=policy),
                RepairDisposition.RETRY,
            )
            self.assertEqual(
                decide_repair(kind, attempt=1, replan_count=0, policy=policy),
                RepairDisposition.RETRY,
            )

            # attempt >= 2, replan_count < 1 -> REPLAN
            self.assertEqual(
                decide_repair(kind, attempt=2, replan_count=0, policy=policy),
                RepairDisposition.REPLAN,
            )
            self.assertEqual(
                decide_repair(kind, attempt=3, replan_count=0, policy=policy),
                RepairDisposition.REPLAN,
            )

            # attempt >= 2, replan_count >= 1 -> FAIL
            self.assertEqual(
                decide_repair(kind, attempt=2, replan_count=1, policy=policy),
                RepairDisposition.FAIL,
            )
            self.assertEqual(
                decide_repair(kind, attempt=3, replan_count=2, policy=policy),
                RepairDisposition.FAIL,
            )

    def test_decide_repair_validation_error(self) -> None:
        policy = RepairPolicy(max_retries=2, max_replans=1)
        vkind = FailureKind.VALIDATION_ERROR

        # replan_count < 1 -> REPLAN regardless of attempt
        self.assertEqual(
            decide_repair(vkind, attempt=0, replan_count=0, policy=policy),
            RepairDisposition.REPLAN,
        )
        self.assertEqual(
            decide_repair("VALIDATION_ERROR", attempt=5, replan_count=0, policy=policy),
            RepairDisposition.REPLAN,
        )

        # replan_count >= 1 -> FAIL
        self.assertEqual(
            decide_repair(vkind, attempt=0, replan_count=1, policy=policy),
            RepairDisposition.FAIL,
        )
        self.assertEqual(
            decide_repair(vkind, attempt=2, replan_count=2, policy=policy),
            RepairDisposition.FAIL,
        )

    def test_decide_repair_unknown_kind(self) -> None:
        self.assertEqual(
            decide_repair(FailureKind.UNKNOWN, attempt=0, replan_count=0),
            RepairDisposition.FAIL,
        )
        self.assertEqual(
            decide_repair("SOME_UNRECOGNIZED_FAILURE", attempt=0, replan_count=0),
            RepairDisposition.FAIL,
        )

    def test_decide_repair_zero_policy_boundaries(self) -> None:
        zero_policy = RepairPolicy(max_retries=0, max_replans=0)

        self.assertEqual(
            decide_repair(FailureKind.CYCLE_FAILED, attempt=0, replan_count=0, policy=zero_policy),
            RepairDisposition.FAIL,
        )
        self.assertEqual(
            decide_repair(FailureKind.VALIDATION_ERROR, attempt=0, replan_count=0, policy=zero_policy),
            RepairDisposition.FAIL,
        )

        replan_only_policy = RepairPolicy(max_retries=0, max_replans=2)
        self.assertEqual(
            decide_repair(FailureKind.CYCLE_FAILED, attempt=0, replan_count=0, policy=replan_only_policy),
            RepairDisposition.REPLAN,
        )

    def test_decide_repair_argument_validation(self) -> None:
        with self.assertRaises(ValueError):
            decide_repair(FailureKind.UNKNOWN, attempt=-1, replan_count=0)

        with self.assertRaises(ValueError):
            decide_repair(FailureKind.UNKNOWN, attempt=0, replan_count=-1)

        with self.assertRaises(ValueError):
            decide_repair(FailureKind.UNKNOWN, attempt=True, replan_count=0)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            decide_repair(FailureKind.UNKNOWN, attempt=0, replan_count=True)  # type: ignore[arg-type]

        with self.assertRaises(ValueError):
            decide_repair(FailureKind.UNKNOWN, attempt=0, replan_count=0, policy="invalid")  # type: ignore[arg-type]

    def test_classify_failure_mapping(self) -> None:
        self.assertEqual(classify_failure(ProviderQuotaError("quota exceeded")), FailureKind.PROVIDER_QUOTA)
        self.assertEqual(classify_failure(HumanInputRequired("need feedback")), FailureKind.HUMAN_INPUT)
        self.assertEqual(classify_failure(CycleTimedOut("timed out")), FailureKind.CYCLE_TIMEOUT)
        self.assertEqual(classify_failure(CycleFailed("failed")), FailureKind.CYCLE_FAILED)
        self.assertEqual(classify_failure(ProviderError("generic provider error")), FailureKind.PROVIDER_ERROR)
        self.assertEqual(classify_failure(ProviderUnauthorizedError("unauthorized")), FailureKind.PROVIDER_ERROR)
        self.assertEqual(classify_failure(ValueError("invalid arg")), FailureKind.VALIDATION_ERROR)

    def test_classify_failure_unknown_exceptions(self) -> None:
        self.assertEqual(classify_failure(RuntimeError("runtime error")), FailureKind.UNKNOWN)
        self.assertEqual(classify_failure(KeyError("key error")), FailureKind.UNKNOWN)
        self.assertEqual(classify_failure(Exception("base exception")), FailureKind.UNKNOWN)

    def test_classify_failure_subclass_ordering(self) -> None:
        # ProviderQuotaError inherits from ProviderError; confirm it's mapped to PROVIDER_QUOTA, not PROVIDER_ERROR
        quota_err = ProviderQuotaError("quota exceeded")
        self.assertTrue(isinstance(quota_err, ProviderError))
        self.assertEqual(classify_failure(quota_err), FailureKind.PROVIDER_QUOTA)


if __name__ == "__main__":
    unittest.main()
