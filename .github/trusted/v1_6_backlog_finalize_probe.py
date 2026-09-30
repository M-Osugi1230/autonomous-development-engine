from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from ade.development_memory import (
    DevelopmentMemoryLedger,
    DevelopmentMemoryRecord,
    MemoryKind,
)
from ade.development_memory_store import DevelopmentMemoryStore

SCRIPT = Path(".github/trusted/v1_6_backlog_finalize.py")
spec = importlib.util.spec_from_file_location("v1_6_backlog_finalize_probe_module", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "a" * 40


def main() -> int:
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
    store = DevelopmentMemoryStore(
        ledger=DevelopmentMemoryLedger(records=(record,))
    )
    chain = module._reconstruct_chain(
        source_store_payload=store.canonical_dict()
    )
    assert chain["candidate"].repository == REPO
    assert chain["candidate"].source_sha == SHA
    assert chain["selection"].selected_candidate_id == chain["candidate"].candidate_id
    assert chain["handoff"].request.allowed_path_prefixes == ("tests",)
    assert chain["handoff"].request.min_tasks == 1
    assert chain["handoff"].request.max_tasks == 1
    assert chain["handoff"].canonical_dict()["execution_authority"] is False
    assert chain["handoff"].canonical_dict()["accepted_plan_authority"] is False
    assert chain["handoff"].canonical_dict()["auto_dispatch"] is False

    print(
        json.dumps(
            {
                "ok": True,
                "immutable_source_memory_required": True,
                "single_candidate_reconstructed": True,
                "tests_only_goal": True,
                "one_task_bound": True,
                "retirement_finalizer_authority": "evidence-only",
                "execution_authority": False,
                "accepted_plan_authority": False,
                "auto_dispatch": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
