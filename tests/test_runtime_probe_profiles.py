from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"
JQUANTS = "M-Osugi1230/jquants-research-studio"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "runtime_probes.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_probes_profile_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_probes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeProbeProfileTests(unittest.TestCase):
    def test_legacy_profile_is_stable(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy("example/target")
        registry = module.build_runtime_probe_registry(
            target_repository="example/target",
        )
        self.assertEqual(
            policy.required_probe_ids,
            ("offline-cli-smoke", "production-import-smoke"),
        )
        self.assertEqual(
            registry.probe_ids,
            ("offline-cli-smoke", "production-import-smoke"),
        )

    def test_jquants_profile_is_target_specific(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(JQUANTS)
        registry = module.build_runtime_probe_registry(
            target_repository=JQUANTS,
        )
        self.assertEqual(
            policy.required_probe_ids,
            (
                "jquants-api-import-smoke",
                "jquants-vercel-contract-smoke",
            ),
        )
        self.assertEqual(
            registry.probe_ids,
            (
                "jquants-api-import-smoke",
                "jquants-vercel-contract-smoke",
            ),
        )

    def test_target_profiles_do_not_grant_runtime_authority(self) -> None:
        module = load_module()
        registry = module.build_runtime_probe_registry(
            target_repository=JQUANTS,
        )
        for registration in registry.canonical_dict()["registrations"]:
            self.assertNotIn("command", registration)
            self.assertNotIn("credentials", registration)
            self.assertNotIn("url", registration)


if __name__ == "__main__":
    unittest.main()
