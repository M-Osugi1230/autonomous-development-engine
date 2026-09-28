from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.remote_execution import (
    RemoteExecutionReceipt,
    execution_target_from_state,
    parse_pull_request_url,
)


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
        "unsafe_target_rejected": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
