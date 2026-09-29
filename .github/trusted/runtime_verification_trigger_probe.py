from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import remote_pr_monitor
from ade.remote_execution import RemoteExecutionReceipt


TARGET = "M-Osugi1230/one-minute-thought-experiments"
MERGE_SHA = "a" * 40


class FakeGitHub:
    def __init__(self) -> None:
        self.files: dict[str, dict] = {}
        self.writes: list[tuple[str, dict, str, str]] = []
        self.dispatches: list[tuple[str, dict]] = []

    def get_json_file(self, path: str, *, ref: str = "main"):
        if path not in self.files:
            raise remote_pr_monitor.GitHubError("GitHub HTTP 404: not found")
        return self.files[path], "fake-sha"

    def upsert_json_file(
        self,
        path: str,
        payload: dict,
        *,
        message: str,
        branch: str = "main",
    ) -> None:
        self.files[path] = payload
        self.writes.append((path, payload, message, branch))

    def dispatch(self, event_type: str, payload: dict | None = None) -> None:
        self.dispatches.append((event_type, payload or {}))


def _remote_receipt() -> RemoteExecutionReceipt:
    return RemoteExecutionReceipt(
        task_id="v14-proof-001",
        target_repository=TARGET,
        pull_request_url=f"https://github.com/{TARGET}/pull/15",
        recorded_at="2026-09-29T00:00:00+00:00",
        status="PR_CREATED",
    )


def main() -> int:
    gh = FakeGitHub()
    state = {
        "metadata": {
            "phase": "v1.4-runtime-deployment-verification",
            "target_repository": TARGET,
        }
    }

    first = remote_pr_monitor._arm_post_merge_runtime_verification(
        gh,
        state=state,
        receipt=_remote_receipt(),
        trusted_merge_sha=MERGE_SHA,
    )
    assert first is not None
    assert first.source_sha == MERGE_SHA
    assert first.status == "DISPATCHED"
    assert first.dispatch_count == 1

    contract_path = ".autodev/runtime-verification/v14-proof-001/contract.json"
    receipt_path = ".autodev/runtime-verification/v14-proof-001/receipt.json"
    assert gh.files[contract_path]["source_sha"] == MERGE_SHA
    assert gh.files[receipt_path]["source_sha"] == MERGE_SHA
    assert gh.files[receipt_path]["status"] == "DISPATCHED"
    assert gh.dispatches == [
        (
            "ade_runtime_verification",
            {
                "task_id": "v14-proof-001",
                "verification_id": f"rv-{MERGE_SHA}",
                "target_repository": TARGET,
                "source_sha": MERGE_SHA,
                "source": "remote-pr-monitor",
            },
        )
    ]

    replay = remote_pr_monitor._arm_post_merge_runtime_verification(
        gh,
        state=state,
        receipt=_remote_receipt(),
        trusted_merge_sha=MERGE_SHA,
    )
    assert replay == first
    assert len(gh.dispatches) == 1

    old_phase = remote_pr_monitor._arm_post_merge_runtime_verification(
        gh,
        state={"metadata": {"phase": "v1.3-repository-intelligence"}},
        receipt=RemoteExecutionReceipt(
            task_id="legacy-task",
            target_repository=TARGET,
            pull_request_url=f"https://github.com/{TARGET}/pull/16",
            recorded_at="2026-09-29T00:00:00+00:00",
            status="PR_CREATED",
        ),
        trusted_merge_sha="b" * 40,
    )
    assert old_phase is None
    assert len(gh.dispatches) == 1

    print(json.dumps({
        "ok": True,
        "exact_merge_sha_bound": True,
        "durable_contract_persisted": True,
        "durable_receipt_persisted": True,
        "post_merge_dispatch_recorded": True,
        "duplicate_dispatch_suppressed": True,
        "pre_v1_4_behavior_preserved": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
