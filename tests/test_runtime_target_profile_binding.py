from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DIR = ROOT / ".github" / "trusted"
CHU_KEI = "M-Osugi1230/chu-kei"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "runtime_verification_dispatch_targeted.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_target_profile_binding_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            "unable to load runtime_verification_dispatch_targeted.py"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeTargetProfileBindingTests(unittest.TestCase):
    def test_repository_dispatch_target_is_bound_for_legacy_one_arg_call(self) -> None:
        module = load_module()
        event = {
            "client_payload": {
                "task_id": "ckpd004-001",
                "target_repository": CHU_KEI,
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            event_path = Path(temp_dir) / "event.json"
            event_path.write_text(
                json.dumps(event),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"GITHUB_EVENT_PATH": str(event_path)},
                clear=False,
            ):
                registry = module.build_target_runtime_probe_registry()

        self.assertEqual(
            registry.probe_ids,
            ("chu-plan-detection-candidate-contract",),
        )

    def test_explicit_target_repository_does_not_require_event_file(self) -> None:
        module = load_module()
        with patch.dict(os.environ, {}, clear=False):
            previous = os.environ.pop("GITHUB_EVENT_PATH", None)
            try:
                registry = module.build_target_runtime_probe_registry(
                    target_repository=CHU_KEI,
                )
            finally:
                if previous is not None:
                    os.environ["GITHUB_EVENT_PATH"] = previous

        self.assertEqual(
            registry.probe_ids,
            ("chu-plan-detection-candidate-contract",),
        )

    def test_chu_kei_registry_uses_v2_implementation_fingerprint(self) -> None:
        module = load_module()
        registry = module.build_target_runtime_probe_registry(
            target_repository=CHU_KEI,
        )
        canonical = registry.canonical_dict()
        self.assertEqual(
            canonical["registrations"],
            [
                {
                    "probe_id": "chu-plan-detection-candidate-contract",
                    "implementation_id": "chu-plan-detection-candidate-contract-v2",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
