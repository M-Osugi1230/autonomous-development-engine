from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_store import DevelopmentMemoryStore

SCRIPT = Path(__file__).resolve().parents[1] / ".github/trusted/v1_6_backlog_finalize.py"
spec = importlib.util.spec_from_file_location("v1_6_backlog_finalize", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def source_store() -> DevelopmentMemoryStore:
    record = DevelopmentMemoryRecord(
        memory_id="mem-" + "1" * 24,
        kind=MemoryKind.VERIFIED_OUTCOME,
        repository=REPO,
        source_sha=SHA,
        statement=(
            "Trusted runtime verification completed with every required probe "
            "passing against the exact source SHA."
        ),
        task_id="v15mem2-001",
        evidence_paths=(
            ".autodev/runtime-verification/v15mem2-001/contract.json",
            ".autodev/runtime-verification/v15mem2-001/receipt.json",
            ".autodev/runtime-verification/v15mem2-001/report.json",
        ),
        evidence_fingerprints=("1" * 64, "2" * 64, "3" * 64),
        tags=("feedback", "runtime", "verified"),
    )
    return DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=(record,))
    )


class FakeGitHub:
    def __init__(self, files: dict[str, dict] | None = None) -> None:
        self.files = dict(files or {})
        self.writes: list[tuple[str, dict, str]] = []

    def get_json_file(self, path: str, *, ref: str = "main"):
        if path not in self.files:
            raise module.GitHubError("GitHub HTTP 404: not found")
        return self.files[path], "fake-sha"

    def put_json_file(
        self,
        path: str,
        payload: dict,
        *,
        sha: str | None,
        message: str,
        branch: str = "main",
    ) -> None:
        self.files[path] = payload
        self.writes.append((path, dict(payload), message))


class V16BacklogFinalizeTests(unittest.TestCase):
    def test_graduated_state_is_terminal_noop_guard(self) -> None:
        self.assertTrue(
            module._v1_6_already_graduated(
                {
                    "status": "READY",
                    "metadata": {
                        "phase": module.PHASE,
                        "v1_6_graduated": True,
                    },
                }
            )
        )
        self.assertFalse(
            module._v1_6_already_graduated(
                {
                    "status": "READY",
                    "metadata": {
                        "phase": module.PHASE,
                        "v1_6_graduated": False,
                    },
                }
            )
        )
        self.assertFalse(
            module._v1_6_already_graduated(
                {"status": "READY", "metadata": {}}
            )
        )
        with self.assertRaisesRegex(ValueError, "ProjectState"):
            module._v1_6_already_graduated([])

    def test_reconstruct_chain_is_deterministic_and_tests_only(self) -> None:
        payload = source_store().canonical_dict()
        left = module._reconstruct_chain(source_store_payload=payload)
        right = module._reconstruct_chain(source_store_payload=payload)
        self.assertEqual(
            left["candidate"].canonical_dict(),
            right["candidate"].canonical_dict(),
        )
        self.assertEqual(
            left["handoff"].canonical_dict(),
            right["handoff"].canonical_dict(),
        )
        self.assertEqual(left["candidate"].source_sha, SHA)
        self.assertEqual(
            left["handoff"].request.allowed_path_prefixes,
            ("tests",),
        )
        self.assertEqual(left["handoff"].request.min_tasks, 1)
        self.assertEqual(left["handoff"].request.max_tasks, 1)

    def test_reconstruct_chain_requires_exact_proof002_verified_memory(self) -> None:
        record = source_store().ledger.records[0]
        other = DevelopmentMemoryRecord(
            memory_id=record.memory_id,
            kind=record.kind,
            repository=record.repository,
            source_sha=record.source_sha,
            statement=record.statement,
            task_id="other-task",
            evidence_paths=record.evidence_paths,
            evidence_fingerprints=record.evidence_fingerprints,
            tags=record.tags,
        )
        store = DevelopmentMemoryStore(
            ledger=DevelopmentMemoryLedger(records=(other,))
        )
        with self.assertRaisesRegex(ValueError, "uniquely bound"):
            module._reconstruct_chain(
                source_store_payload=store.canonical_dict(),
            )

    def test_write_once_is_idempotent_and_rejects_drift(self) -> None:
        path = ".autodev/autonomous-backlog/proof/example.json"
        payload = {"schema_version": 1, "value": "same"}
        gh = FakeGitHub()
        module._write_once_json(
            gh,
            path,
            payload,
            message="proof",
        )
        self.assertEqual(gh.files[path], payload)
        self.assertEqual(len(gh.writes), 1)

        module._write_once_json(
            gh,
            path,
            payload,
            message="proof replay",
        )
        self.assertEqual(len(gh.writes), 1)

        with self.assertRaisesRegex(ValueError, "artifact drift"):
            module._write_once_json(
                gh,
                path,
                {"schema_version": 1, "value": "different"},
                message="bad",
            )

    def test_target_observations_requires_exact_accepted_path(self) -> None:
        original = module._api_json
        try:
            def fake_api(path: str):
                if "/pulls/21/files" in path:
                    return [{"filename": "tests/test_pipeline.py"}]
                if "/pulls/21" in path:
                    return {
                        "state": "closed",
                        "merged_at": "2026-10-01T00:02:00Z",
                        "created_at": "2026-10-01T00:00:00Z",
                        "html_url": f"https://github.com/{REPO}/pull/21",
                        "head": {"sha": "b" * 40},
                        "base": {"sha": SHA},
                        "merge_commit_sha": "c" * 40,
                    }
                if "/actions/runs" in path:
                    return {
                        "workflow_runs": [
                            {
                                "id": 101,
                                "name": "Phase 1 and 2 checks",
                                "event": "pull_request",
                                "conclusion": "success",
                                "head_sha": "b" * 40,
                                "created_at": "2026-10-01T00:00:30Z",
                                "updated_at": "2026-10-01T00:01:00Z",
                            },
                            {
                                "id": 102,
                                "name": "ADE Remote PR Gate",
                                "event": "workflow_run",
                                "conclusion": "success",
                                "head_sha": "d" * 40,
                                "created_at": "2026-10-01T00:01:10Z",
                                "updated_at": "2026-10-01T00:01:30Z",
                            },
                        ]
                    }
                raise AssertionError(path)

            module._api_json = fake_api
            remote = module.RemoteExecutionReceipt(
                task_id="proof-task",
                target_repository=REPO,
                pull_request_url=f"https://github.com/{REPO}/pull/21",
                recorded_at="2026-10-01T00:02:00+00:00",
                status="MERGED",
            )
            observed = module._target_observations(
                remote=remote,
                expected_base_sha=SHA,
                expected_changed_paths=("tests/test_pipeline.py",),
            )
            self.assertEqual(
                observed["changed_paths"],
                ["tests/test_pipeline.py"],
            )
            with self.assertRaisesRegex(ValueError, "scope is not exact"):
                module._target_observations(
                    remote=remote,
                    expected_base_sha=SHA,
                    expected_changed_paths=("tests/test_models.py",),
                )
        finally:
            module._api_json = original

    def test_canonical_task_defaults_are_safely_equivalent(self) -> None:
        omitted = {
            "allowed_paths": ["tests/test_pipeline.py"],
        }
        self.assertEqual(omitted.get("new_paths", []), [])
        self.assertIs(omitted.get("human_only", False), False)

        explicit_bad_new = {
            "new_paths": ["tests/new_file.py"],
            "human_only": False,
        }
        explicit_bad_human = {
            "new_paths": [],
            "human_only": True,
        }
        self.assertNotEqual(explicit_bad_new.get("new_paths", []), [])
        self.assertIsNot(explicit_bad_human.get("human_only", False), False)

    def test_positive_run_id_accepts_durable_string_or_int_only(self) -> None:
        self.assertEqual(module._positive_int(7, field="run"), 7)
        self.assertEqual(module._positive_int("8", field="run"), 8)
        for value in (0, "0", "", None, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    module._positive_int(value, field="run")


if __name__ == "__main__":
    unittest.main()
