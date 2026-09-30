from __future__ import annotations

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_client import GitHubClient, GitHubError
from scripts.v1_5_development_memory_audit import (
    DEFAULT_EVIDENCE,
    audit as audit_v1_5,
)

BRANCH = "ade-v1-5-graduation-closeout"
MARKER = "ADE_TRUSTED_GRADUATION_CLOSEOUT:v1.5"
RESULT_PATH = Path(".autodev/runtime/v1-5-graduation-closeout-result.json")
STATE_PATH = ".autodev/state.json"
CI_PATH = ".github/workflows/ci.yml"
ACCEPTANCE_PATH = "ACCEPTANCE.md"
ROADMAP_PATH = "ROADMAP.md"


def _write_result(payload: dict[str, Any]) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _get_ref(gh: GitHubClient, branch: str) -> dict[str, Any] | None:
    try:
        payload = gh._request(
            "GET",
            f"/repos/{gh.repository}/git/ref/heads/{branch}",
        )
    except GitHubError as exc:
        if "GitHub HTTP 404:" in str(exc):
            return None
        raise
    if not isinstance(payload, dict):
        raise GitHubError("branch ref response must be an object")
    return payload


def _open_closeout_prs(gh: GitHubClient) -> list[dict[str, Any]]:
    owner = gh.repository.split("/", 1)[0]
    payload = gh._request(
        "GET",
        f"/repos/{gh.repository}/pulls?state=open&head={owner}:{BRANCH}&per_page=10",
    )
    if not isinstance(payload, list):
        raise GitHubError("pull request list response must be a list")
    return [item for item in payload if isinstance(item, dict)]


def _put_text(
    gh: GitHubClient,
    *,
    path: str,
    content: str,
    sha: str,
    message: str,
) -> None:
    gh._request(
        "PUT",
        f"/repos/{gh.repository}/contents/{path}",
        {
            "message": message,
            "content": _encode(content),
            "sha": sha,
            "branch": BRANCH,
        },
    )


def _ci_text(value: str) -> str:
    if "ADE v1.5 Development Memory Graduation audit" in value:
        next_value = value
    else:
        anchor = """      - name: ADE v1.4 Runtime Verification Graduation audit
        env:
          PYTHONPATH: src
        run: python scripts/v1_4_runtime_verification_audit.py
"""
        addition = anchor + """
      - name: ADE v1.5 Development Memory Graduation audit
        env:
          PYTHONPATH: src
        run: python scripts/v1_5_development_memory_audit.py
"""
        if anchor not in value:
            raise ValueError("CI v1.4 graduation audit anchor is missing")
        next_value = value.replace(anchor, addition)

    if "workflow_dispatch:" not in next_value:
        anchor = """on:
  pull_request:
"""
        replacement = """on:
  pull_request:
  workflow_dispatch:
"""
        if anchor not in next_value:
            raise ValueError("CI trigger anchor is missing")
        next_value = next_value.replace(anchor, replacement, 1)
    return next_value


def _acceptance_text(value: str) -> str:
    lines = (
        "- [ ] A successor real external-repository proof reuses records directly from `.autodev/development-memory.json`, with exact reused record fingerprints persisted before execution and no scope/Acceptance authority gained from memory.",
        "- [ ] A dedicated v1.5 Graduation audit proves the trusted memory path end to end, including durable-store reuse rather than bootstrap evidence reuse alone.",
    )
    next_value = value
    for line in lines:
        if line in next_value:
            next_value = next_value.replace(line, line.replace("[ ]", "[x]"), 1)
        elif line.replace("[ ]", "[x]") not in next_value:
            raise ValueError("v1.5 Acceptance closeout line is missing")
    return next_value


def _roadmap_text(value: str, evidence: dict[str, Any]) -> str:
    next_value = value.replace(
        "## ADE v1.5 — Development Memory 🚧",
        "## ADE v1.5 — Development Memory ✅",
        1,
    )
    if "## ADE v1.5 — Development Memory ✅" not in next_value:
        raise ValueError("v1.5 ROADMAP heading is missing")
    if "v1.5 Graduation complete:" not in next_value:
        runtime = evidence.get("runtime_verification")
        runtime = runtime if isinstance(runtime, dict) else {}
        receipt = runtime.get("receipt")
        receipt = receipt if isinstance(receipt, dict) else {}
        task = evidence.get("task")
        task = task if isinstance(task, dict) else {}
        note = (
            "\nv1.5 Graduation complete: proof002 reused the proof001 durable "
            "Development Memory record by exact ID/fingerprint before execution, "
            "completed the trusted external-repository loop, and reached exact-SHA "
            f"Runtime Verification `{receipt.get('status')}` at merge "
            f"`{task.get('merge_commit')}`. Final evidence is frozen at "
            f"`{DEFAULT_EVIDENCE}` and the v1.5 audit is mandatory in CI.\n"
        )
        insert_at = next_value.find("## ADE v1.6")
        if insert_at < 0:
            next_value = next_value.rstrip() + note + "\n"
        else:
            next_value = (
                next_value[:insert_at].rstrip()
                + note
                + "\n\n"
                + next_value[insert_at:]
            )
    return next_value


def _graduated_state(
    state: dict[str, Any],
    *,
    evidence_path: str,
) -> dict[str, Any]:
    if state.get("status") != "READY":
        raise ValueError("v1.5 closeout requires READY ProjectState")
    if state.get("current_task_id") is not None:
        raise ValueError("v1.5 closeout requires no active task")
    if state.get("failed_task_ids") != []:
        raise ValueError("v1.5 closeout requires failed=0")
    next_state = dict(state)
    metadata = state.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata.update(
        {
            "v1_5_graduated": True,
            "v1_5_graduated_at": datetime.now(UTC).isoformat(),
            "v1_5_graduation_evidence": evidence_path,
            "milestone": "v1.5-graduated",
            "next_system_action": "arm-v1.6-autonomous-backlog",
            "next_required_human_action": None,
        }
    )
    metadata.pop("pause_reason", None)
    metadata.pop("resume_after", None)
    next_state["metadata"] = metadata
    next_state["status"] = "READY"
    next_state["current_task_id"] = None
    next_state["failed_task_ids"] = []
    return next_state


def main() -> int:
    try:
        audit_result = audit_v1_5(Path("."))
        if not audit_result.get("v1_5_development_memory_graduated"):
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.5-graduation-audit-not-green",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        evidence = json.loads(
            Path(DEFAULT_EVIDENCE).read_text(encoding="utf-8")
        )
        if not isinstance(evidence, dict):
            raise ValueError("v1.5 graduation evidence must be an object")

        gh = GitHubClient()
        state, _ = gh.get_json_file(STATE_PATH)
        metadata = state.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        if metadata.get("v1_5_graduated") is True:
            result = {
                "schema_version": 1,
                "state": "NOOP",
                "reason": "v1.5-already-graduated",
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        prs = _open_closeout_prs(gh)
        if len(prs) > 1:
            raise ValueError("multiple open v1.5 graduation closeout PRs")
        if len(prs) == 1:
            pr = prs[0]
            head = pr.get("head")
            head = head if isinstance(head, dict) else {}
            head_sha = head.get("sha")
            if not isinstance(head_sha, str) or len(head_sha) != 40:
                raise ValueError("existing closeout PR has invalid head SHA")
            gh._request(
                "POST",
                f"/repos/{gh.repository}/actions/workflows/ci.yml/dispatches",
                {"ref": BRANCH},
            )
            result = {
                "schema_version": 1,
                "state": "CI_DISPATCHED",
                "reason": "existing-closeout-pr",
                "pull_request": pr.get("number"),
                "head_sha": head_sha,
            }
            _write_result(result)
            print(json.dumps(result, sort_keys=True))
            return 0

        existing_ref = _get_ref(gh, BRANCH)
        if existing_ref is not None:
            raise ValueError(
                "stale v1.5 graduation closeout branch exists without PR"
            )

        base_sha = gh.get_branch_head_sha(gh.repository, branch="main")
        gh._request(
            "POST",
            f"/repos/{gh.repository}/git/refs",
            {"ref": f"refs/heads/{BRANCH}", "sha": base_sha},
        )

        ci_text, ci_sha = gh.get_text_file(
            gh.repository,
            path=CI_PATH,
            ref=base_sha,
            max_bytes=131072,
        )
        acceptance_text, acceptance_sha = gh.get_text_file(
            gh.repository,
            path=ACCEPTANCE_PATH,
            ref=base_sha,
            max_bytes=131072,
        )
        roadmap_text, roadmap_sha = gh.get_text_file(
            gh.repository,
            path=ROADMAP_PATH,
            ref=base_sha,
            max_bytes=131072,
        )
        state_payload, state_sha = gh.get_json_file(
            STATE_PATH,
            ref=base_sha,
        )

        _put_text(
            gh,
            path=CI_PATH,
            content=_ci_text(ci_text),
            sha=ci_sha,
            message="v1.5: require Development Memory graduation audit",
        )
        _put_text(
            gh,
            path=ACCEPTANCE_PATH,
            content=_acceptance_text(acceptance_text),
            sha=acceptance_sha,
            message="v1.5: close Development Memory acceptance",
        )
        _put_text(
            gh,
            path=ROADMAP_PATH,
            content=_roadmap_text(roadmap_text, evidence),
            sha=roadmap_sha,
            message="v1.5: graduate Development Memory",
        )
        gh.put_json_file(
            STATE_PATH,
            _graduated_state(state_payload, evidence_path=DEFAULT_EVIDENCE),
            sha=state_sha,
            message="state: graduate ADE v1.5 Development Memory",
            branch=BRANCH,
        )

        pr = gh._request(
            "POST",
            f"/repos/{gh.repository}/pulls",
            {
                "title": "ADE v1.5: graduate Development Memory",
                "head": BRANCH,
                "base": "main",
                "body": (
                    f"{MARKER}\n\n"
                    "Trusted closeout generated only after the frozen proof002 "
                    "evidence passes the v1.5 Graduation audit. CI is explicitly "
                    "dispatched on this branch before the dedicated graduation "
                    "gate may merge it."
                ),
            },
        )
        if not isinstance(pr, dict) or type(pr.get("number")) is not int:
            raise GitHubError("closeout pull request response is invalid")

        gh._request(
            "POST",
            f"/repos/{gh.repository}/actions/workflows/ci.yml/dispatches",
            {"ref": BRANCH},
        )
        result = {
            "schema_version": 1,
            "state": "CI_DISPATCHED",
            "reason": "v1.5-closeout-pr-created",
            "pull_request": pr["number"],
            "base_sha": base_sha,
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True))
        return 0

    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": 1,
            "state": "FAILED",
            "reason": str(exc).splitlines()[0][:256],
        }
        _write_result(result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
