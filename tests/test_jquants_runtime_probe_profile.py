from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"
JQUANTS = "M-Osugi1230/jquants-research-studio"
JICHI = "M-Osugi1230/jichi-insight"
GENERIC = "example/target"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "runtime_probes.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_jquants_runtime_probes_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_probes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class JQuantsRuntimeProbeProfileTests(unittest.TestCase):
    def test_jquants_profile_requires_api_and_vercel_contract(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(JQUANTS)
        registry = module.build_runtime_probe_registry(
            target_repository=JQUANTS,
        )
        expected = (
            "jquants-api-import-smoke",
            "jquants-vercel-contract-smoke",
        )
        self.assertEqual(policy.required_probe_ids, expected)
        self.assertEqual(registry.probe_ids, expected)

    def test_existing_jichi_profile_is_preserved(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(JICHI)
        registry = module.build_runtime_probe_registry(
            target_repository=JICHI,
        )
        expected = (
            "jichi-data-contract-smoke",
            "jichi-next-contract-smoke",
        )
        self.assertEqual(policy.required_probe_ids, expected)
        self.assertEqual(registry.probe_ids, expected)

    def test_generic_profile_remains_repository_aware(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(GENERIC)
        registry = module.build_runtime_probe_registry(
            target_repository=GENERIC,
        )
        self.assertEqual(
            policy.required_probe_ids,
            ("repository-bytecode-smoke", "repository-entrypoint-smoke"),
        )
        self.assertIn("repository-bytecode-smoke", registry.probe_ids)
        self.assertIn("repository-entrypoint-smoke", registry.probe_ids)

    def test_jquants_profile_does_not_encode_runtime_authority(self) -> None:
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
