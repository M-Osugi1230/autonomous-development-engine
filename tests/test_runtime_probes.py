from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "runtime_probes.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_probes_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_probes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RuntimeProbesTests(unittest.TestCase):
    def test_generic_external_policy_uses_repository_probes(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(
            "example/private-production-repo"
        )
        self.assertEqual(
            policy.required_probe_ids,
            (
                "repository-bytecode-smoke",
                "repository-entrypoint-smoke",
            ),
        )

    def test_legacy_thought_pipeline_policy_is_preserved(self) -> None:
        module = load_module()
        policy = module.build_runtime_verification_policy(
            "M-Osugi1230/one-minute-thought-experiments"
        )
        self.assertEqual(
            policy.required_probe_ids,
            (
                "offline-cli-smoke",
                "production-import-smoke",
            ),
        )

    def test_vercel_entrypoint_is_resolved_from_pyproject(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                (
                    "[project]\n"
                    "name='demo-app'\n"
                    "[tool.vercel]\n"
                    "entrypoint='app:app'\n"
                ),
                encoding="utf-8",
            )
            workspace = module.PreparedRuntimeWorkspace(
                root=root,
                python_executable=Path(sys.executable),
                dependency_fingerprint="a" * 64,
                source_sha="b" * 40,
            )
            self.assertEqual(
                module._repository_entrypoint(workspace),
                ("app", "app"),
            )

    def test_project_package_is_fallback_entrypoint(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "src" / "demo_app"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                "[project]\nname='demo-app'\n",
                encoding="utf-8",
            )
            workspace = module.PreparedRuntimeWorkspace(
                root=root,
                python_executable=Path(sys.executable),
                dependency_fingerprint="a" * 64,
                source_sha="b" * 40,
            )
            self.assertEqual(
                module._repository_entrypoint(workspace),
                ("demo_app", None),
            )


if __name__ == "__main__":
    unittest.main()
