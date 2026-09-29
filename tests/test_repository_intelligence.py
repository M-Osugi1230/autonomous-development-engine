from __future__ import annotations

import json
import unittest

from ade.repository_intelligence import (
    RepositoryIntelligenceError,
    build_repository_snapshot,
    planner_repository_context,
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
