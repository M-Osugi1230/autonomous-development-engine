from __future__ import annotations

import json
import unittest

from ade.repository_intelligence import (
    RepositoryIntelligenceError,
    analyze_python_source,
    build_python_content_summary,
    build_repository_snapshot,
    planner_repository_context,
    python_candidate_paths,
)


SHA = "a" * 40
PATHS = [
    "README.md",
    "pyproject.toml",
    ".github/workflows/ci.yml",
    "src/ade/__init__.py",
    "src/ade/autonomous_planner.py",
    "src/ade/models.py",
    "tests/test_autonomous_planner.py",
    "tests/test_models.py",
    "docs/architecture.md",
]


class RepositoryIntelligenceTests(unittest.TestCase):
    def test_snapshot_is_deterministic_and_classified(self) -> None:
        first = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=PATHS,
        )
        second = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=reversed(PATHS),
        )
        self.assertEqual(first.paths, second.paths)
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(first.source_roots, ("src",))
        self.assertEqual(first.test_roots, ("tests",))
        self.assertEqual(first.manifest_paths, ("pyproject.toml",))
        self.assertEqual(first.workflow_paths, (".github/workflows/ci.yml",))
        self.assertEqual(
            first.documentation_paths,
            ("README.md", "docs/architecture.md"),
        )

    def test_context_exposes_only_files_within_trusted_roots(self) -> None:
        snapshot = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=PATHS,
        )
        context = planner_repository_context(
            snapshot,
            allowed_path_prefixes=("src/ade", "tests"),
        )
        payload = json.loads(context.serialized)
        self.assertEqual(payload["repository"], "example/repo")
        self.assertEqual(payload["source_sha"], SHA)
        self.assertEqual(
            payload["known_files_within_trusted_roots"],
            [
                "src/ade/__init__.py",
                "src/ade/autonomous_planner.py",
                "src/ade/models.py",
                "tests/test_autonomous_planner.py",
                "tests/test_models.py",
            ],
        )
        self.assertNotIn(".github/workflows/ci.yml", payload["known_files_within_trusted_roots"])
        self.assertEqual(context.fingerprint, __import__("hashlib").sha256(
            context.serialized.encode("utf-8")
        ).hexdigest())

    def test_context_truncation_is_deterministic(self) -> None:
        paths = [f"src/ade/file_{index:03d}.py" for index in range(20)]
        snapshot = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=paths,
        )
        context = planner_repository_context(
            snapshot,
            allowed_path_prefixes=("src/ade",),
            max_files=3,
        )
        self.assertEqual(
            context.payload["known_files_within_trusted_roots"],
            [
                "src/ade/file_000.py",
                "src/ade/file_001.py",
                "src/ade/file_002.py",
            ],
        )
        self.assertEqual(context.payload["known_file_count_within_trusted_roots"], 20)
        self.assertTrue(context.payload["known_files_truncated"])

    def test_unsafe_or_duplicate_paths_are_rejected(self) -> None:
        for path in ("/etc/passwd", "../escape.py", "src\\escape.py", "src/a\n.py"):
            with self.subTest(path=path):
                with self.assertRaises(RepositoryIntelligenceError):
                    build_repository_snapshot(
                        repository="example/repo",
                        base_branch="main",
                        source_sha=SHA,
                        paths=[path],
                    )

        with self.assertRaisesRegex(RepositoryIntelligenceError, "duplicate"):
            build_repository_snapshot(
                repository="example/repo",
                base_branch="main",
                source_sha=SHA,
                paths=["src/a.py", "src/a.py"],
            )

    def test_python_candidate_paths_are_bounded_and_scope_filtered(self) -> None:
        snapshot = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=[
                "src/ade/a.py",
                "src/ade/b.py",
                "src/ade/data.json",
                "tests/test_a.py",
                ".github/trusted/gate.py",
            ],
        )
        self.assertEqual(
            python_candidate_paths(
                snapshot,
                allowed_path_prefixes=("src/ade", "tests"),
                max_files=2,
            ),
            ("src/ade/a.py", "src/ade/b.py"),
        )

    def test_python_summary_extracts_only_safe_structure(self) -> None:
        source = '''"""Bearer secret-should-never-appear in summary."""

import os
import json as js
from .models import ProjectState
from package.submodule import Thing

API_TOKEN = "super-secret-value"

class Worker:
    pass

def build_value():
    return API_TOKEN

async def run_async():
    return None
'''
        summary = analyze_python_source(
            path="src/ade/example.py",
            source=source,
            content_sha="b" * 40,
        )
        self.assertTrue(summary.parse_ok)
        self.assertEqual(summary.module, "ade.example")
        self.assertFalse(summary.is_test)
        self.assertEqual(
            [(item.kind, item.name) for item in summary.symbols],
            [
                ("class", "Worker"),
                ("function", "build_value"),
                ("function", "run_async"),
            ],
        )
        self.assertEqual(
            summary.imports,
            (".models", "json", "os", "package.submodule"),
        )
        serialized = json.dumps(summary.canonical_dict(), sort_keys=True)
        self.assertNotIn("secret-should-never-appear", serialized)
        self.assertNotIn("super-secret-value", serialized)
        self.assertNotIn("ProjectState", serialized)
        self.assertNotIn("Thing", serialized)

    def test_python_summary_syntax_error_does_not_leak_source(self) -> None:
        source = 'SECRET_VALUE = "do-not-leak"\ndef broken(:\n    pass\n'
        summary = analyze_python_source(
            path="tests/test_broken.py",
            source=source,
            content_sha="c" * 40,
        )
        self.assertFalse(summary.parse_ok)
        self.assertTrue(summary.is_test)
        self.assertEqual(summary.symbols, ())
        self.assertEqual(summary.imports, ())
        self.assertNotIn(
            "do-not-leak",
            json.dumps(summary.canonical_dict(), sort_keys=True),
        )

    def test_python_content_summary_is_order_independent(self) -> None:
        files = [
            (
                "tests/test_helper.py",
                "from ade.helper import helper\n\ndef test_helper():\n    assert helper()\n",
                "d" * 40,
            ),
            (
                "src/ade/helper.py",
                "def helper():\n    return 1\n",
                "e" * 40,
            ),
        ]
        first = build_python_content_summary(files)
        second = build_python_content_summary(reversed(files))
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())
        self.assertEqual(
            [module.path for module in first.modules],
            ["src/ade/helper.py", "tests/test_helper.py"],
        )

    def test_python_source_character_budget_is_enforced(self) -> None:
        with self.assertRaisesRegex(RepositoryIntelligenceError, "character budget"):
            analyze_python_source(
                path="src/ade/large.py",
                source="x" * 11,
                content_sha="f" * 40,
                max_source_chars=10,
            )

    def test_tree_budget_is_enforced(self) -> None:
        with self.assertRaisesRegex(RepositoryIntelligenceError, "path budget"):
            build_repository_snapshot(
                repository="example/repo",
                base_branch="main",
                source_sha=SHA,
                paths=["src/a.py", "src/b.py"],
                max_paths=1,
            )


if __name__ == "__main__":
    unittest.main()
