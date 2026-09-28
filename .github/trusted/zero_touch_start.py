from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.zero_touch_start import StartDecision, StartDisposition, evaluate_zero_touch_start
from github_client import GitHubClient, GitHubError

ACCEPTED_PLAN_PATH = Path(".autodev/accepted-plan.json")
CAMPAIGN_PATH = Path(".autodev/campaign.json")
GRAPH_PATH = Path(".autodev/task-graph.json")
STATE_PATH = Path(".autodev/state.json")
CYCLE_TASK_PATH = Path(".autodev/cycle-task.json")
LEASE_PATH = Path(".autodev/runtime/execution-lease.json")
CHECKPOINT_PATH = Path(".autodev/runtime/checkpoint.json")
RECEIPT_PATH = ".autodev/runtime/zero-touch-start.json"
LOCAL_RECEIPT_PATH = Path(RECEIPT_PATH)
RESULT_PATH = Path(".autodev/runtime/zero-touch-start-result.json")


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load(path)


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_message(exc: BaseException) -> str:
    value = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
    for name in ("GITHUB_TOKEN", "JULES_API_KEY"):
        secret = os.environ.get(name)
        if secret:
            value = value.replace(secret, "[REDACTED]")
    return value[:256]


def _missing_plan_result() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "disposition": StartDisposition.NOOP.value,
        "reason": "accepted-plan-missing",
        "campaign_id": None,
        "task_id": None,
        "plan_fingerprint": None,
    }


def _receipt(decision: StartDecision, previous: dict[str, Any] | None, now: datetime) -> dict[str, Any]:
    count = 1
    if (
        previous is not None
        and previous.get("schema_version") == 1
        and previous.get("campaign_id") == decision.campaign_id
        and previous.get("task_id") == decision.task_id
        and previous.get("plan_fingerprint") == decision.plan_fingerprint
    ):
        raw_count = previous.get("dispatch_count", 0)
        if type(raw_count) is int and raw_count >= 0:
            count = raw_count + 1
    return {
        "schema_version": 1,
        "status": "DISPATCHED",
        "campaign_id": decision.campaign_id,
        "task_id": decision.task_id,
        "plan_fingerprint": decision.plan_fingerprint,
        "dispatch_count": count,
        "dispatched_at": now.astimezone(UTC).isoformat(),
        "source": os.environ.get("GITHUB_EVENT_NAME", "unknown"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    }


def main() -> int:
    if not ACCEPTED_PLAN_PATH.exists():
        result = _missing_plan_result()
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    now = datetime.now(UTC)
    try:
        decision = evaluate_zero_touch_start(
            accepted_plan_payload=_load(ACCEPTED_PLAN_PATH),
            campaign_payload=_load(CAMPAIGN_PATH),
            graph_payload=_load(GRAPH_PATH),
            state_payload=_load(STATE_PATH),
            cycle_task_payload=_load(CYCLE_TASK_PATH),
            lease_payload=_optional(LEASE_PATH),
            checkpoint_payload=_optional(CHECKPOINT_PATH),
            receipt_payload=_optional(LOCAL_RECEIPT_PATH),
            now=now,
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as exc:
        result = {
            "schema_version": 1,
            "disposition": StartDisposition.BLOCKED.value,
            "reason": "validation-error",
            "detail": _safe_message(exc),
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    result = decision.to_dict()
    _write_result(result)
    print(json.dumps(result, sort_keys=True))
    if not decision.should_dispatch:
        return 0

    if decision.task_id is None:
        raise RuntimeError("dispatch decision requires task_id")

    try:
        gh = GitHubClient()
        gh.dispatch(
            "ade_next_cycle",
            {
                "task_id": decision.task_id,
                "campaign_id": decision.campaign_id,
                "source": "zero-touch-start",
            },
        )
        previous = _optional(LOCAL_RECEIPT_PATH)
        receipt = _receipt(decision, previous, now)
        gh.upsert_json_file(
            RECEIPT_PATH,
            receipt,
            message=f"zero-touch: dispatch {decision.task_id}",
        )
        _write_result({**result, "receipt": receipt})
        try:
            gh.dispatch(
                "ade_mission_control_refresh",
                {
                    "task_id": decision.task_id,
                    "campaign_id": decision.campaign_id,
                },
            )
        except GitHubError as exc:
            print(f"WARNING: Mission Control refresh dispatch failed: {_safe_message(exc)}", file=sys.stderr)
        print(f"DISPATCHED: {decision.campaign_id}/{decision.task_id}")
        return 0
    except GitHubError as exc:
        failed = {
            **result,
            "dispatch_error": _safe_message(exc),
        }
        _write_result(failed)
        print(f"Zero-touch dispatch failed: {_safe_message(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
