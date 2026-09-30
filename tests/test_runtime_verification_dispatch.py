from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from ade.runtime_verification import RuntimeVerificationContract
from ade.runtime_verification_trigger import RuntimeVerificationReceipt


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"
SHA = "a" * 40


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "runtime_verification_dispatch.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_verification_dispatch_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime verification dispatch module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeVerificationDispatchTests(unittest.TestCase):
    def _values(self):
        contract = RuntimeVerificationContract(
            verification_id=f"rv-{SHA}",
            target_repository="example/target",
            source_sha=SHA,
            environment="repository",
            required_probe_ids=("offline-cli-smoke",),
            max_attempts=2,
            timeout_seconds=300,
        )
        receipt = RuntimeVerificationReceipt(
            verification_id=contract.verification_id,
            task_id="task-001",
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            contract_fingerprint=contract.fingerprint(),
            registry_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            status="ARMED",
            dispatch_count=0,
        )
        event = {
            "task_id": receipt.task_id,
            "verification_id": receipt.verification_id,
            "target_repository": receipt.target_repository,
            "source_sha": receipt.source_sha,
            "source": "remote-pr-monitor",
        }
        return contract, receipt, event

    def test_exact_dispatch_payload_is_accepted(self) -> None:
        module = load_module()
        contract, receipt, event = self._values()
        module.validate_dispatch_payload(
            event_payload=event,
            contract=contract,
            receipt=receipt,
        )

    def test_stale_or_cross_repository_payload_is_rejected(self) -> None:
        module = load_module()
        contract, receipt, event = self._values()
        for key, value in (
            ("task_id", "task-002"),
            ("verification_id", f"rv-{'d' * 40}"),
            ("target_repository", "other/target"),
            ("source_sha", "d" * 40),
        ):
            with self.subTest(key=key):
                changed = dict(event)
                changed[key] = value
                with self.assertRaises(ValueError):
                    module.validate_dispatch_payload(
                        event_payload=changed,
                        contract=contract,
                        receipt=receipt,
                    )

    def test_verified_v15_bootstrap_feedback_dispatches_successor(self) -> None:
        module = load_module()
        contract, _, _ = self._values()
        receipt = RuntimeVerificationReceipt(
            verification_id=contract.verification_id,
            task_id="v15mem1-001",
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            contract_fingerprint=contract.fingerprint(),
            registry_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            status="VERIFIED",
            dispatch_count=1,
        )

        class FakeGitHub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def dispatch(self, event_type: str, payload: dict) -> None:
                self.calls.append((event_type, dict(payload)))

        gh = FakeGitHub()
        outcome = module._dispatch_development_memory_successor(
            gh,
            receipt=receipt,
            memory_feedback={"state": "ADDED"},
        )
        self.assertEqual(outcome, "DISPATCHED")
        self.assertEqual(len(gh.calls), 1)
        self.assertEqual(gh.calls[0][0], "ade_development_memory_successor")
        self.assertEqual(gh.calls[0][1]["task_id"], "v15mem1-001")

    def test_successor_dispatch_is_not_runtime_success_authority(self) -> None:
        module = load_module()
        contract, _, _ = self._values()
        ordinary = RuntimeVerificationReceipt(
            verification_id=contract.verification_id,
            task_id="other-task",
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            contract_fingerprint=contract.fingerprint(),
            registry_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            status="VERIFIED",
            dispatch_count=1,
        )

        class FakeGitHub:
            def dispatch(self, event_type: str, payload: dict) -> None:
                raise AssertionError("dispatch must not be called")

        self.assertEqual(
            module._dispatch_development_memory_successor(
                FakeGitHub(),
                receipt=ordinary,
                memory_feedback={"state": "ADDED"},
            ),
            "NOT_APPLICABLE",
        )

        bootstrap = RuntimeVerificationReceipt(
            verification_id=contract.verification_id,
            task_id="v15mem1-001",
            target_repository=contract.target_repository,
            source_sha=contract.source_sha,
            contract_fingerprint=contract.fingerprint(),
            registry_fingerprint="b" * 64,
            policy_fingerprint="c" * 64,
            status="VERIFIED",
            dispatch_count=1,
        )
        self.assertEqual(
            module._dispatch_development_memory_successor(
                FakeGitHub(),
                receipt=bootstrap,
                memory_feedback={"state": "FAILED"},
            ),
            "WAITING_FOR_DURABLE_MEMORY",
        )

    def test_runtime_evidence_paths_reject_unsafe_task_id(self) -> None:
        from ade.runtime_verification_trigger import runtime_verification_paths

        self.assertEqual(
            runtime_verification_paths("task-001"),
            (
                ".autodev/runtime-verification/task-001/contract.json",
                ".autodev/runtime-verification/task-001/receipt.json",
            ),
        )
        for task_id in ("../escape", "task/escape", "", "bad task"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(ValueError):
                    runtime_verification_paths(task_id)


if __name__ == "__main__":
    unittest.main()
