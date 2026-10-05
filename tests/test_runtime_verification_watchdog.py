from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ade.runtime_verification_trigger import RuntimeVerificationReceipt


def load_watchdog():
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "trusted"
        / "runtime_verification_watchdog.py"
    )
    trusted_dir = str(path.parent)
    if trusted_dir not in sys.path:
        sys.path.insert(0, trusted_dir)
    spec = importlib.util.spec_from_file_location(
        "runtime_verification_watchdog_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_verification_watchdog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def receipt(*, task_id: str, status: str) -> RuntimeVerificationReceipt:
    return RuntimeVerificationReceipt(
        verification_id="rv-" + "a" * 40,
        task_id=task_id,
        target_repository="M-Osugi1230/example",
        source_sha="a" * 40,
        contract_fingerprint="b" * 64,
        registry_fingerprint="c" * 64,
        policy_fingerprint="d" * 64,
        status=status,
        dispatch_count=0,
    )


class RuntimeVerificationWatchdogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_watchdog()

    def test_no_current_task_is_noop(self) -> None:
        action, reason = self.module.watchdog_disposition(
            state_payload={"current_task_id": None},
            receipt=None,
        )
        self.assertEqual(action, "NOOP")
        self.assertEqual(reason, "no-current-task")

    def test_armed_current_receipt_is_dispatchable(self) -> None:
        action, reason = self.module.watchdog_disposition(
            state_payload={"current_task_id": "task-001"},
            receipt=receipt(task_id="task-001", status="ARMED"),
        )
        self.assertEqual(action, "DISPATCH")
        self.assertEqual(reason, "armed-runtime-verification")

    def test_nonarmed_receipt_does_not_duplicate_dispatch(self) -> None:
        action, reason = self.module.watchdog_disposition(
            state_payload={"current_task_id": "task-001"},
            receipt=receipt(task_id="task-001", status="DISPATCHED"),
        )
        self.assertEqual(action, "NOOP")
        self.assertEqual(reason, "runtime-receipt-dispatched")

    def test_receipt_for_other_task_is_noop(self) -> None:
        action, reason = self.module.watchdog_disposition(
            state_payload={"current_task_id": "task-002"},
            receipt=receipt(task_id="task-001", status="ARMED"),
        )
        self.assertEqual(action, "NOOP")
        self.assertEqual(reason, "runtime-receipt-not-current")

    def test_probe_registry_uses_target_repository_when_supported(self) -> None:
        sentinel = object()

        def modern_registry(workspace=None, *, target_repository=None):
            self.assertIsNone(workspace)
            self.assertEqual(target_repository, "M-Osugi1230/jichi-insight")
            return sentinel

        with patch.object(
            self.module,
            "build_runtime_probe_registry",
            modern_registry,
        ):
            result = self.module._build_probe_registry(
                "M-Osugi1230/jichi-insight"
            )
        self.assertIs(result, sentinel)

    def test_probe_registry_supports_legacy_control_branch_signature(self) -> None:
        sentinel = object()

        def legacy_registry(workspace=None):
            self.assertIsNone(workspace)
            return sentinel

        with patch.object(
            self.module,
            "build_runtime_probe_registry",
            legacy_registry,
        ):
            result = self.module._build_probe_registry(
                "M-Osugi1230/chu-kei"
            )
        self.assertIs(result, sentinel)


if __name__ == "__main__":
    unittest.main()
