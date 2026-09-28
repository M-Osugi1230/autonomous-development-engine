from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ade.remote_execution import RemoteExecutionReceipt
from ade_pr_gate import advance_queue
from github_client import GitHubClient, GitHubError
from observability import record_merged_pr

RECEIPT_PATH = Path(".autodev/runtime/remote-execution.json")
RESULT_PATH = Path(".autodev/runtime/remote-monitor-result.json")
STATE_PATH = ".autodev/state.json"
POLL_SECONDS = 15
MAX_POLLS = 80


def _write(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_receipt() -> RemoteExecutionReceipt | None:
    if not RECEIPT_PATH.exists():
        return None
    payload = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    return RemoteExecutionReceipt.from_dict(payload)


def _public_github_json(path: str) -> dict[str, Any]:
    request = Request(
        "https://api.github.com" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ADE-Remote-Monitor/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"target GitHub HTTP {exc.code}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"target GitHub network error: {exc.reason}") from exc
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("target GitHub response must be an object")
    return payload


def _persist_merged_receipt(
    gh: GitHubClient,
    receipt: RemoteExecutionReceipt,
) -> None:
    merged = RemoteExecutionReceipt(
        task_id=receipt.task_id,
        target_repository=receipt.target_repository,
        pull_request_url=receipt.pull_request_url,
        recorded_at=datetime.now(UTC).isoformat(),
        status="MERGED",
    )
    gh.upsert_json_file(
        ".autodev/runtime/remote-execution.json",
        merged.to_dict(),
        message=f"remote: merged {receipt.task_id}",
    )


def main() -> int:
    receipt = _load_receipt()
    if receipt is None:
        result = {"schema_version": 1, "state": "NOOP", "reason": "remote-receipt-missing"}
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    gh = GitHubClient()
    state, _ = gh.get_json_file(STATE_PATH)
    current_task_id = state.get("current_task_id")
    if current_task_id != receipt.task_id:
        result = {
            "schema_version": 1,
            "state": "NOOP",
            "reason": "remote-receipt-not-current",
            "receipt_task_id": receipt.task_id,
            "current_task_id": current_task_id,
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    if receipt.status == "MERGED":
        result = {
            "schema_version": 1,
            "state": "NOOP",
            "reason": "remote-receipt-already-merged",
            "task_id": receipt.task_id,
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    owner, repo = receipt.target_repository.split("/", 1)
    pr_number = receipt.pull_request_number

    try:
        for _ in range(MAX_POLLS):
            pr = _public_github_json(f"/repos/{owner}/{repo}/pulls/{pr_number}")
            html_url = pr.get("html_url")
            if html_url != receipt.pull_request_url:
                raise RuntimeError("target pull request URL does not match receipt")

            base = pr.get("base")
            base_ref = base.get("ref") if isinstance(base, dict) else None
            metadata = state.get("metadata", {})
            expected_base = (
                metadata.get("target_base_branch")
                if isinstance(metadata, dict)
                else None
            )
            if isinstance(expected_base, str) and expected_base and base_ref != expected_base:
                raise RuntimeError("target pull request base branch does not match planner request")

            if pr.get("merged_at"):
                head = pr.get("head", {})
                head_sha = head.get("sha") if isinstance(head, dict) else None
                if not isinstance(head_sha, str) or not head_sha:
                    raise RuntimeError("merged target pull request has no head SHA")

                next_task_id = advance_queue(
                    gh,
                    completed_task_id=receipt.task_id,
                )
                try:
                    record_merged_pr(
                        gh,
                        pr_number=pr_number,
                        pr_url=receipt.pull_request_url,
                        task_id=receipt.task_id,
                        head_sha=head_sha,
                        occurred_at=datetime.now(UTC).isoformat(),
                    )
                except (GitHubError, ValueError) as exc:
                    print(f"WARNING: remote observability update failed: {exc}", file=sys.stderr)

                _persist_merged_receipt(gh, receipt)
                result = {
                    "schema_version": 1,
                    "state": "MERGED",
                    "task_id": receipt.task_id,
                    "target_repository": receipt.target_repository,
                    "pull_request_number": pr_number,
                    "next_task_id": next_task_id,
                }
                _write(result)
                print(json.dumps(result, sort_keys=True))
                return 0

            if pr.get("state") == "closed":
                result = {
                    "schema_version": 1,
                    "state": "HUMAN_WAIT",
                    "reason": "target-pull-request-closed-without-merge",
                    "task_id": receipt.task_id,
                    "target_repository": receipt.target_repository,
                    "pull_request_number": pr_number,
                }
                _write(result)
                print(json.dumps(result, sort_keys=True))
                return 2

            time.sleep(POLL_SECONDS)

        result = {
            "schema_version": 1,
            "state": "WAITING",
            "reason": "target-pull-request-not-merged-yet",
            "task_id": receipt.task_id,
            "target_repository": receipt.target_repository,
            "pull_request_number": pr_number,
        }
        _write(result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RuntimeError, GitHubError, ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "task_id": receipt.task_id,
            "error": str(exc).splitlines()[0][:256],
        }
        _write(result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
