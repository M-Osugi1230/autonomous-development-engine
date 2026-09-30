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
    path = TRUSTED_DIR / "v1_5_memory_successor.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_5_memory_successor_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1_5_memory_successor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verified_receipt() -> RuntimeVerificationReceipt:
    contract = RuntimeVerificationContract(
        verification_id="rv-" + SHA,
        target_repository="M-Osugi1230/one-minute-thought-experiments",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=2,
        timeout_seconds=300,
    )
    return RuntimeVerificationReceipt(
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


class TrustedV15MemorySuccessorTests(unittest.TestCase):
    def test_verified_receipt_replays_only_runtime_feedback_path(self) -> None:
        module = load_module()

        class FakeGitHub:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            def dispatch(self, event_type: str, payload: dict) -> None:
                self.calls.append((event_type, dict(payload)))

        gh = FakeGitHub()
        result = module._retry_verified_memory_feedback(
            gh,
            receipt_payload=verified_receipt().canonical_dict(),
        )
        self.assertEqual(result, "DISPATCHED")
        self.assertEqual(len(gh.calls), 1)
        event_type, payload = gh.calls[0]
        self.assertEqual(event_type, "ade_runtime_verification")
        self.assertEqual(payload["task_id"], "v15mem1-001")
        self.assertEqual(payload["source_sha"], SHA)
        self.assertEqual(
            payload["source"],
            "development-memory-successor-feedback-retry",
        )

    def test_nonverified_or_other_task_cannot_replay_feedback(self) -> None:
        module = load_module()

        class FakeGitHub:
            def dispatch(self, event_type: str, payload: dict) -> None:
                raise AssertionError("dispatch must not be called")

        receipt = verified_receipt().canonical_dict()
        receipt["status"] = "FAILED"
        self.assertEqual(
            module._retry_verified_memory_feedback(
                FakeGitHub(),
                receipt_payload=receipt,
            ),
            "NOT_APPLICABLE",
        )

        receipt = verified_receipt().canonical_dict()
        receipt["task_id"] = "other-task"
        self.assertEqual(
            module._retry_verified_memory_feedback(
                FakeGitHub(),
                receipt_payload=receipt,
            ),
            "NOT_APPLICABLE",
        )

    def test_dispatch_failure_uses_scheduled_retry(self) -> None:
        module = load_module()

        class FailingGitHub:
            def dispatch(self, event_type: str, payload: dict) -> None:
                raise module.GitHubError("network")

        self.assertEqual(
            module._retry_verified_memory_feedback(
                FailingGitHub(),
                receipt_payload=verified_receipt().canonical_dict(),
            ),
            "SCHEDULED_RETRY",
        )


if __name__ == "__main__":
    unittest.main()
