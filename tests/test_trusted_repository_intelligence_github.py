from __future__ import annotations

import base64
import importlib.util
import sys
import unittest
from pathlib import Path


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_github_client():
    path = TRUSTED_DIR / "github_client.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_github_repository_intelligence_test_module",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load trusted github_client.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeGitHubClient:
    pass


class TrustedGitHubRepositoryIntelligenceTests(unittest.TestCase):
    def _client(self, responses: list[object]):
        module = load_github_client()

        class Client(module.GitHubClient):
            def __init__(self):
                super().__init__(
                    repository="controller/repo",
                    token="test-token",
                    sleep=lambda _: None,
                )
                self.responses = list(responses)
                self.requests: list[tuple[str, str]] = []

            def _request(self, method, path, payload=None):
                self.requests.append((method, path))
                if not self.responses:
                    raise AssertionError("unexpected request")
                return self.responses.pop(0)

        return module, Client()

    def test_reads_branch_sha_and_blob_tree_paths(self) -> None:
        sha = "a" * 40
        module, client = self._client(
            [
                {"commit": {"sha": sha}},
                {
                    "truncated": False,
                    "tree": [
                        {"type": "tree", "path": "src"},
                        {"type": "blob", "path": "src/app.py"},
                        {"type": "blob", "path": "tests/test_app.py"},
                    ],
                },
            ]
        )
        self.assertEqual(
            client.get_branch_head_sha("example/target", branch="main"),
            sha,
        )
        self.assertEqual(
            client.list_tree_paths("example/target", tree_sha=sha),
            ["src/app.py", "tests/test_app.py"],
        )
        self.assertEqual(
            client.requests,
            [
                ("GET", "/repos/example/target/branches/main"),
                ("GET", f"/repos/example/target/git/trees/{sha}?recursive=1"),
            ],
        )
        self.assertTrue(issubclass(module.GitHubError, RuntimeError))

    def test_reads_bounded_utf8_text_file(self) -> None:
        raw = b"def helper():\n    return 1\n"
        blob_sha = "d" * 40
        module, client = self._client(
            [
                {
                    "size": len(raw),
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode("ascii"),
                    "sha": blob_sha,
                }
            ]
        )
        text_value, returned_sha = client.get_text_file(
            "example/target",
            path="src/helper.py",
            ref="a" * 40,
            max_bytes=1024,
        )
        self.assertEqual(text_value, raw.decode("utf-8"))
        self.assertEqual(returned_sha, blob_sha)
        self.assertEqual(
            client.requests,
            [
                (
                    "GET",
                    "/repos/example/target/contents/src/helper.py?ref=" + "a" * 40,
                )
            ],
        )
        self.assertTrue(issubclass(module.GitHubError, RuntimeError))

    def test_rejects_oversized_or_non_utf8_file(self) -> None:
        module, oversized = self._client(
            [
                {
                    "size": 2048,
                    "encoding": "base64",
                    "content": "",
                    "sha": "e" * 40,
                }
            ]
        )
        with self.assertRaisesRegex(module.GitHubError, "byte budget"):
            oversized.get_text_file(
                "example/target",
                path="src/large.py",
                ref="a" * 40,
                max_bytes=1024,
            )

        raw = b"\xff\xfe"
        module, binary = self._client(
            [
                {
                    "size": len(raw),
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode("ascii"),
                    "sha": "f" * 40,
                }
            ]
        )
        with self.assertRaisesRegex(module.GitHubError, "UTF-8"):
            binary.get_text_file(
                "example/target",
                path="src/binary.py",
                ref="a" * 40,
                max_bytes=1024,
            )

    def test_truncated_tree_is_rejected(self) -> None:
        sha = "b" * 40
        module, client = self._client(
            [{"truncated": True, "tree": [{"type": "blob", "path": "src/app.py"}]}]
        )
        with self.assertRaisesRegex(module.GitHubError, "truncated"):
            client.list_tree_paths("example/target", tree_sha=sha)

    def test_tree_entry_budget_is_enforced(self) -> None:
        sha = "c" * 40
        module, client = self._client(
            [
                {
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": "src/a.py"},
                        {"type": "blob", "path": "src/b.py"},
                    ],
                }
            ]
        )
        with self.assertRaisesRegex(module.GitHubError, "entry budget"):
            client.list_tree_paths(
                "example/target",
                tree_sha=sha,
                max_entries=1,
            )


if __name__ == "__main__":
    unittest.main()
