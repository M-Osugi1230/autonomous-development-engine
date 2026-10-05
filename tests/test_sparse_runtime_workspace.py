from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ade.runtime_verification import RuntimeVerificationContract, RuntimeVerificationError


TRUSTED = Path(__file__).resolve().parents[1] / ".github" / "trusted"
if str(TRUSTED) not in sys.path:
    sys.path.insert(0, str(TRUSTED))


def load_module():
    path = TRUSTED / "sparse_runtime_workspace.py"
    spec = importlib.util.spec_from_file_location(
        "sparse_runtime_workspace_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load sparse_runtime_workspace.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="rv-" + "a" * 40,
        target_repository="M-Osugi1230/chu-kei",
        source_sha="a" * 40,
        environment="repository",
        required_probe_ids=("chu-plan-detection-candidate-contract",),
        max_attempts=2,
        timeout_seconds=120,
    )


class SparseRuntimeWorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_sparse_workspace_materializes_only_explicit_file(self) -> None:
        path = (
            "operations/plan-detection/candidates/"
            "ade-batch-002/candidates-v1.json"
        )
        data = b'{"schemaVersion":"plan-detection-candidate-batch-v1"}\n'
        with patch.object(self.module, "_download_file", return_value=data) as download:
            workspace = self.module.prepare_sparse_repository_runtime_workspace(
                contract(),
                paths=(path,),
            )
        try:
            self.assertEqual(
                (workspace.root / path).read_bytes(),
                data,
            )
            download.assert_called_once_with(
                "M-Osugi1230/chu-kei",
                "a" * 40,
                path,
            )
            self.assertEqual(workspace.source_sha, "a" * 40)
            self.assertEqual(len(workspace.dependency_fingerprint), 64)
        finally:
            workspace.cleanup()

    def test_sparse_workspace_rejects_parent_escape(self) -> None:
        with self.assertRaises(RuntimeVerificationError):
            self.module.prepare_sparse_repository_runtime_workspace(
                contract(),
                paths=("operations/../secrets.txt",),
            )

    def test_sparse_workspace_rejects_too_many_paths(self) -> None:
        paths = tuple(f"safe/path-{index}.json" for index in range(9))
        with self.assertRaises(RuntimeVerificationError):
            self.module.prepare_sparse_repository_runtime_workspace(
                contract(),
                paths=paths,
            )

    def test_sparse_workspace_rejects_total_byte_budget(self) -> None:
        paths = tuple(f"safe/path-{index}.json" for index in range(5))
        chunk = b"x" * (512 * 1024)
        with patch.object(self.module, "_download_file", return_value=chunk):
            with self.assertRaises(RuntimeVerificationError):
                self.module.prepare_sparse_repository_runtime_workspace(
                    contract(),
                    paths=paths,
                )


if __name__ == "__main__":
    unittest.main()
