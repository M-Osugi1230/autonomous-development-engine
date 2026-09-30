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

    def test_positive_run_id_accepts_durable_string_or_int_only(self) -> None:
        self.assertEqual(module._positive_int(7, field="run"), 7)
        self.assertEqual(module._positive_int("8", field="run"), 8)
        for value in (0, "0", "", None, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    module._positive_int(value, field="run")


if __name__ == "__main__":
    unittest.main()
