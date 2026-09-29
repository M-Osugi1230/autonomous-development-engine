from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import jules_cycle
from ade.remote_execution import (
    RemoteExecutionReceipt,
    execution_target_from_state,
    parse_pull_request_url,
    receipt_binds_pull_request,
)




class FakeGitHub:
    def __init__(self):
        self.repository = "M-Osugi1230/autonomous-development-engine"
        self.receipt = None
        self.writes = []
        self.dispatches = []

    def get_json_file(self, path, *, ref="main"):
        if self.receipt is None:
            raise jules_cycle.GitHubError("GitHub HTTP 404: not found")
        return self.receipt, "receipt-sha"

    def upsert_json_file(self, path, payload, *, message, branch="main"):
        self.receipt = payload
        self.writes.append((path, payload, message, branch))

    def dispatch(self, event_type, payload=None):
        self.dispatches.append((event_type, payload or {}))


def main() -> int:
    target = execution_target_from_state(
        {
            "metadata": {
                "target_repository": "M-Osugi1230/one-minute-thought-experiments"
            }
        },
        fallback_repository="M-Osugi1230/autonomous-development-engine",
    )
    assert target == "M-Osugi1230/one-minute-thought-experiments"

    receipt = RemoteExecutionReceipt(
        task_id="v12ext-001",
        target_repository=target,
        pull_request_url=(
            "https://github.com/M-Osugi1230/one-minute-thought-experiments/pull/7"
        ),
        recorded_at="2026-09-29T00:00:00+00:00",
    )
    repository, number = parse_pull_request_url(receipt.pull_request_url)
    assert repository == target
    assert number == 7
    assert RemoteExecutionReceipt.from_dict(receipt.to_dict()) == receipt
    assert receipt_binds_pull_request(
        receipt.to_dict(),
        task_id="v12ext-001",
        target_repository=target,
        pull_request_url=receipt.pull_request_url,
    )
    assert not receipt_binds_pull_request(
        receipt.to_dict(),
        task_id="v12ext-002",
        target_repository=target,
        pull_request_url=receipt.pull_request_url,
    )

    gh = FakeGitHub()
    jules_cycle._persist_remote_execution(
        gh,
        task_id="v12ext-001",
        target_repository=target,
        pull_request_url=receipt.pull_request_url,
    )
    assert len(gh.writes) == 1
    assert gh.dispatches == [
        (
            "ade_remote_pr_monitor",
            {
                "task_id": "v12ext-001",
                "target_repository": target,
                "pull_request_url": receipt.pull_request_url,
                "source": "jules-cycle",
            },
        )
    ]
    jules_cycle._persist_remote_execution(
        gh,
        task_id="v12ext-001",
        target_repository=target,
        pull_request_url=receipt.pull_request_url,
    )
    assert len(gh.writes) == 1
    assert len(gh.dispatches) == 1

    try:
        execution_target_from_state(
            {"metadata": {"target_repository": "../escape"}},
            fallback_repository="M-Osugi1230/autonomous-development-engine",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe target repository was accepted")

    print(json.dumps({
        "ok": True,
        "state_bound_target": True,
        "strict_pr_url": True,
        "receipt_round_trip": True,
        "idempotent_pr_binding": True,
        "unsafe_target_rejected": True,
        "explicit_remote_monitor_dispatch": True,
        "duplicate_monitor_dispatch_suppressed": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
