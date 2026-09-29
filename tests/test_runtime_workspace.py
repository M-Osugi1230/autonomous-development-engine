from __future__ import annotations

from io import BytesIO
import importlib.util
import tarfile
import sys
import tempfile
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_workspace_module():
    path = TRUSTED_DIR / "runtime_workspace.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_runtime_workspace_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load runtime_workspace.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def archive_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return buffer.getvalue()


class RuntimeWorkspaceTests(unittest.TestCase):
    def test_extracts_single_root_archive_safely(self) -> None:
        module = load_workspace_module()
        data = archive_bytes(
            {
                "owner-repo-sha/pyproject.toml": b"[project]\nname='demo'\ndependencies=[]\n",
                "owner-repo-sha/src/demo.py": b"x = 1\n",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "checkout"
            module._extract_archive(data, destination)
            self.assertTrue((destination / "pyproject.toml").is_file())
            self.assertEqual(
                (destination / "src" / "demo.py").read_text(encoding="utf-8"),
                "x = 1\n",
            )

    def test_archive_links_are_rejected(self) -> None:
        module = load_workspace_module()
        buffer = BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            root = tarfile.TarInfo("owner-repo-sha")
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
            link = tarfile.TarInfo("owner-repo-sha/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            archive.addfile(link)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(module.RuntimeVerificationError, "links/devices"):
                module._extract_archive(buffer.getvalue(), Path(tmp) / "checkout")

    def test_simple_pypi_dependencies_are_allowlisted(self) -> None:
        module = load_workspace_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text(
                """
[project]
name = "demo"
dependencies = [
  "PyYAML>=6.0.2,<7.0.0",
  "pydantic>=2.10.0,<3.0.0",
]
""".strip()
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                module._safe_dependency_specs(root),
                (
                    "PyYAML>=6.0.2,<7.0.0",
                    "pydantic>=2.10.0,<3.0.0",
                ),
            )

    def test_url_or_marker_dependency_is_rejected(self) -> None:
        module = load_workspace_module()
        for dependency in (
            "demo @ https://example.invalid/demo.whl",
            "demo;python_version>='3.11'",
            "../local-package",
        ):
            with self.subTest(dependency=dependency), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "pyproject.toml").write_text(
                    (
                        "[project]\n"
                        "name='demo'\n"
                        f"dependencies=[{dependency!r}]\n"
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(module.RuntimeVerificationError):
                    module._safe_dependency_specs(root)


if __name__ == "__main__":
    unittest.main()
