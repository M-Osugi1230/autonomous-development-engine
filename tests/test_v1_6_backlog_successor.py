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

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github/trusted/v1_6_backlog_successor.py"
)
spec = importlib.util.spec_from_file_location("v1_6_backlog_successor", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def memory(
    *,
    task_id: str = "v15mem2-001",
    kind: MemoryKind = MemoryKind.VERIFIED_OUTCOME,
    tags: tuple[str, ...] = ("feedback", "runtime", "verified"),
) -> DevelopmentMemoryRecord:
    return DevelopmentMemoryRecord(
        memory_id="mem-" + "1" * 24,
        kind=kind,
        repository=REPO,
        source_sha=SHA,
        statement=(
            "Trusted runtime verification completed with every required probe "
            "passing against the exact source SHA."
        ),
        task_id=task_id,
        evidence_paths=(
            ".autodev/runtime-verification/v15mem2-001/contract.json",
            ".autodev/runtime-verification/v15mem2-001/receipt.json",
            ".autodev/runtime-verification/v15mem2-001/report.json",
        ),
        evidence_fingerprints=("1" * 64, "2" * 64, "3" * 64),
        tags=tags,
    )


def store(record: DevelopmentMemoryRecord | None = None) -> DevelopmentMemoryStore:
    return DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(
            records=((record or memory()),)
        )
    )


def state(*, graduated: bool = True, status: str = "READY") -> dict:
    return {
        "schema_version": 1,
        "project_id": "autonomous-development-engine",
        "status": status,
        "current_task_id": None,
        "completed_task_ids": ["v15mem2-001"],
        "failed_task_ids": [],
        "metadata": {
            "phase": "v1.5-development-memory",
            "v1_5_graduated": graduated,
        },
    }


class V16BacklogSuccessorTests(unittest.TestCase):
    def test_graduated_v15_proof002_memory_builds_tests_only_goal(self) -> None:
        source_store = store()
        activation = module.build_activation(
            state_payload=state(),
            store_payload=source_store.canonical_dict(),
        )
        self.assertEqual(
            activation["source_store_fingerprint"],
            source_store.fingerprint(),
        )
        self.assertEqual(
            activation["source_memory_id"],
            source_store.ledger.records[0].memory_id,
        )
        self.assertEqual(activation["source_sha"], SHA)
        self.assertEqual(activation["backlog"]["candidate_count"], 1)
        self.assertEqual(
            activation["selection"]["selected_candidate_id"],
            activation["candidate_id"],
        )
        self.assertEqual(
            activation["planning_goal"]["target_repository"],
            REPO,
        )
        self.assertEqual(
            activation["planning_goal"]["allowed_path_prefixes"],
            ["tests"],
        )
        self.assertEqual(activation["planning_goal"].get("min_tasks", 1), 1)
        self.assertEqual(activation["planning_goal"]["max_tasks"], 1)
        self.assertTrue(
            activation["request_id"].startswith("abgproof-request-")
        )
        self.assertTrue(
            activation["campaign_id"].startswith("abgproof-campaign-")
        )
        self.assertFalse(
            activation["handoff"]["execution_authority"]
        )
        self.assertFalse(
            activation["handoff"]["accepted_plan_authority"]
        )
        self.assertFalse(activation["handoff"]["auto_dispatch"])

    def test_activation_is_deterministic(self) -> None:
        payload = store().canonical_dict()
        left = module.build_activation(
            state_payload=state(),
            store_payload=payload,
        )
        right = module.build_activation(
            state_payload=state(),
            store_payload=payload,
        )
        self.assertEqual(left, right)

    def test_local_pregraduation_state_is_safe_noop_gate(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / module.STATE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(state(graduated=False)),
                encoding="utf-8",
            )
            self.assertFalse(module._local_v1_5_graduated(root))

            path.write_text(
                json.dumps(state(graduated=True)),
                encoding="utf-8",
            )
            self.assertTrue(module._local_v1_5_graduated(root))

    def test_v15_graduation_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "not graduated"):
            module.build_activation(
                state_payload=state(graduated=False),
                store_payload=store().canonical_dict(),
            )

    def test_clean_ready_state_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "READY"):
            module.build_activation(
                state_payload=state(status="PAUSED_QUOTA"),
                store_payload=store().canonical_dict(),
            )

        dirty = state()
        dirty["failed_task_ids"] = ["v15mem2-001"]
        with self.assertRaisesRegex(ValueError, "failed tasks"):
            module.build_activation(
                state_payload=dirty,
                store_payload=store().canonical_dict(),
            )

    def test_exact_proof002_verified_outcome_memory_is_required(self) -> None:
        for record in (
            memory(task_id="other-task"),
            memory(kind=MemoryKind.FAILURE),
            memory(tags=("feedback", "runtime")),
        ):
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    module.build_activation(
                        state_payload=state(),
                        store_payload=store(record).canonical_dict(),
                    )

    def test_ambiguous_proof002_memory_records_fail_closed(self) -> None:
        first = memory()
        second = DevelopmentMemoryRecord(
            memory_id="mem-" + "2" * 24,
            kind=MemoryKind.VERIFIED_OUTCOME,
            repository=REPO,
            source_sha=SHA,
            statement=first.statement,
            task_id="v15mem2-001",
            evidence_paths=first.evidence_paths,
            evidence_fingerprints=("4" * 64, "5" * 64, "6" * 64),
            tags=first.tags,
        )
        ambiguous = DevelopmentMemoryStore(
            ledger=DevelopmentMemoryLedger(records=(first, second))
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            module.build_activation(
                state_payload=state(),
                store_payload=ambiguous.canonical_dict(),
            )


if __name__ == "__main__":
    unittest.main()
