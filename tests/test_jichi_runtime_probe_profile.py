from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRUSTED_DIR = ROOT / ".github" / "trusted"
SRC_DIR = ROOT / "src"
for value in (str(SRC_DIR), str(TRUSTED_DIR)):
    if value not in sys.path:
        sys.path.insert(0, value)

from ade.runtime_probe_registry import RuntimeProbeInvocation
from ade.runtime_verification import RuntimeProbeStatus
from runtime_workspace import PreparedRuntimeWorkspace


JICHI = "M-Osugi1230/jichi-insight"


def load_runtime_probes():
    path = TRUSTED_DIR / "runtime_probes.py"
    spec = importlib.util.spec_from_file_location(
        "jichi_runtime_profile_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_probes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class JichiRuntimeProbeProfileTests(unittest.TestCase):
    def test_policy_and_registry_use_jichi_specific_probes(self) -> None:
        module = load_runtime_probes()
        policy = module.build_runtime_verification_policy(JICHI)
        registry = module.build_runtime_probe_registry(
            target_repository=JICHI,
        )

        self.assertEqual(
            policy.required_probe_ids,
            (
                "jichi-data-contract-smoke",
                "jichi-next-contract-smoke",
            ),
        )
        self.assertEqual(
            registry.probe_ids,
            (
                "jichi-data-contract-smoke",
                "jichi-next-contract-smoke",
            ),
        )

    def test_next_contract_accepts_expected_monorepo_shape(self) -> None:
        module = load_runtime_probes()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = root / "apps" / "web"
            app = web / "app"
            app.mkdir(parents=True)
            (app / "layout.tsx").write_text("export default function Layout() {}", encoding="utf-8")
            (app / "page.tsx").write_text("export default function Page() {}", encoding="utf-8")
            (web / "next.config.ts").write_text("export default {}", encoding="utf-8")
            (web / "tsconfig.json").write_text("{}", encoding="utf-8")
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "build": "pnpm --filter @jichi-insight/web build",
                            "lint": "pnpm --filter @jichi-insight/web lint",
                            "typecheck": "pnpm --filter @jichi-insight/web typecheck",
                            "validate:data": "python scripts/validate_repository.py",
                            "test:py": "pytest",
                        }
                    }
                ),
                encoding="utf-8",
            )
            (web / "package.json").write_text(
                json.dumps(
                    {
                        "scripts": {
                            "build": "next build",
                            "start": "next start",
                            "lint": "eslint .",
                            "typecheck": "tsc --noEmit",
                        },
                        "dependencies": {
                            "next": "^16.0.0",
                            "react": "^19.0.0",
                            "react-dom": "^19.0.0",
                        },
                    }
                ),
                encoding="utf-8",
            )
            workspace = PreparedRuntimeWorkspace(
                root=root,
                python_executable=Path(sys.executable),
                dependency_fingerprint="a" * 64,
                source_sha="b" * 40,
            )
            observation = module._jichi_next_contract_runner(workspace)(
                RuntimeProbeInvocation(
                    target_repository=JICHI,
                    source_sha="b" * 40,
                    environment="repository",
                )
            )

        self.assertEqual(observation.status, RuntimeProbeStatus.PASS)
        self.assertEqual(observation.detail_code, "jichi-next-contract-pass")

    def test_next_contract_fails_closed_when_required_app_file_is_missing(self) -> None:
        module = load_runtime_probes()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = root / "apps" / "web"
            web.mkdir(parents=True)
            (root / "package.json").write_text(
                json.dumps({"scripts": {}}),
                encoding="utf-8",
            )
            (web / "package.json").write_text(
                json.dumps({"scripts": {}, "dependencies": {}}),
                encoding="utf-8",
            )
            workspace = PreparedRuntimeWorkspace(
                root=root,
                python_executable=Path(sys.executable),
                dependency_fingerprint="a" * 64,
                source_sha="b" * 40,
            )
            observation = module._jichi_next_contract_runner(workspace)(
                RuntimeProbeInvocation(
                    target_repository=JICHI,
                    source_sha="b" * 40,
                    environment="repository",
                )
            )

        self.assertEqual(observation.status, RuntimeProbeStatus.FAIL)
        self.assertEqual(
            observation.detail_code,
            "jichi-next-app-contract-missing",
        )


if __name__ == "__main__":
    unittest.main()
