from __future__ import annotations

import json
import unittest

from ade.repository_intelligence import (
    RepositoryIntelligenceError,
    analyze_python_source,
    build_python_content_summary,
    build_repository_relationships,
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

    def test_planner_context_includes_only_safe_content_summary(self) -> None:
        snapshot = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=[
                "src/ade/a.py",
                "src/ade/b.py",
                "tests/test_a.py",
            ],
        )
        content = build_python_content_summary(
            [
                (
                    "src/ade/a.py",
                    '"""do-not-leak-docstring"""\nimport os\nSECRET = "do-not-leak-secret"\ndef public_api():\n    return SECRET\n',
                    "1" * 40,
                ),
                (
                    "src/ade/b.py",
                    "from .a import public_api\nclass Service:\n    pass\n",
                    "2" * 40,
                ),
                (
                    "tests/test_a.py",
                    "from ade.a import public_api\ndef test_public_api():\n    assert public_api()\n",
                    "3" * 40,
                ),
            ]
        )
        context = planner_repository_context(
            snapshot,
            allowed_path_prefixes=("src/ade", "tests"),
            content_summary=content,
            max_summary_modules=2,
        )
        payload = context.payload
        self.assertEqual(payload["content_summary_module_count"], 3)
        self.assertTrue(payload["python_module_summaries_truncated"])
        self.assertEqual(
            [item["path"] for item in payload["python_module_summaries"]],
            ["src/ade/a.py", "src/ade/b.py"],
        )
        serialized = context.serialized
        self.assertNotIn("do-not-leak-docstring", serialized)
        self.assertNotIn("do-not-leak-secret", serialized)
        self.assertIn("public_api", serialized)
        self.assertIn("Service", serialized)

    def test_relationship_graph_resolves_internal_imports_and_tests(self) -> None:
        content = build_python_content_summary(
            [
                (
                    "src/pkg/models.py",
                    "class Model:\n    pass\n",
                    "4" * 40,
                ),
                (
                    "src/pkg/service.py",
                    "import os\nfrom .models import Model\nclass Service:\n    pass\n",
                    "5" * 40,
                ),
                (
                    "tests/test_service.py",
                    "from pkg.service import Service\ndef test_service():\n    assert Service\n",
                    "6" * 40,
                ),
                (
                    "tests/test_models.py",
                    "def test_model_shape():\n    assert True\n",
                    "7" * 40,
                ),
            ]
        )
        graph = build_repository_relationships(content)
        self.assertEqual(
            [edge.canonical_dict() for edge in graph.dependency_edges],
            [
                {
                    "source_path": "src/pkg/service.py",
                    "target_path": "src/pkg/models.py",
                    "kind": "import",
                },
                {
                    "source_path": "tests/test_service.py",
                    "target_path": "src/pkg/service.py",
                    "kind": "import",
                },
            ],
        )
        self.assertEqual(
            [link.canonical_dict() for link in graph.test_source_links],
            [
                {
                    "test_path": "tests/test_models.py",
                    "source_path": "src/pkg/models.py",
                    "reason": "filename",
                },
                {
                    "test_path": "tests/test_service.py",
                    "source_path": "src/pkg/service.py",
                    "reason": "import",
                },
            ],
        )
        serialized = json.dumps(graph.canonical_dict(), sort_keys=True)
        self.assertNotIn('"os"', serialized)

    def test_relationship_graph_is_order_independent(self) -> None:
        files = [
            (
                "src/pkg/a.py",
                "from .b import helper\ndef run():\n    return helper()\n",
                "8" * 40,
            ),
            (
                "src/pkg/b.py",
                "def helper():\n    return 1\n",
                "9" * 40,
            ),
            (
                "tests/test_a.py",
                "from pkg.a import run\ndef test_run():\n    assert run()\n",
                "a" * 40,
            ),
        ]
        first = build_repository_relationships(build_python_content_summary(files))
        second = build_repository_relationships(
            build_python_content_summary(reversed(files))
        )
        self.assertEqual(first.canonical_dict(), second.canonical_dict())
        self.assertEqual(first.fingerprint(), second.fingerprint())

    def test_planner_context_contains_bounded_relationships(self) -> None:
        snapshot = build_repository_snapshot(
            repository="example/repo",
            base_branch="main",
            source_sha=SHA,
            paths=[
                "src/pkg/a.py",
                "src/pkg/b.py",
                "tests/test_a.py",
            ],
        )
        content = build_python_content_summary(
            [
                (
                    "src/pkg/a.py",
                    "from .b import helper\ndef run():\n    return helper()\n",
                    "b" * 40,
                ),
                (
                    "src/pkg/b.py",
                    "def helper():\n    return 1\n",
                    "c" * 40,
                ),
                (
                    "tests/test_a.py",
                    "from pkg.a import run\ndef test_run():\n    assert run()\n",
                    "d" * 40,
                ),
            ]
        )
        graph = build_repository_relationships(content)
        context = planner_repository_context(
            snapshot,
            allowed_path_prefixes=("src", "tests"),
            content_summary=content,
            relationship_graph=graph,
            max_relationships=1,
        )
        self.assertEqual(context.payload["internal_dependency_edge_count"], 2)
        self.assertTrue(context.payload["dependency_edges_truncated"])
        self.assertEqual(len(context.payload["internal_dependency_edges"]), 1)
        self.assertEqual(context.payload["test_source_link_count"], 1)
        self.assertFalse(context.payload["test_source_links_truncated"])
        self.assertEqual(
            context.payload["relationship_graph_fingerprint"],
            graph.fingerprint(),
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
