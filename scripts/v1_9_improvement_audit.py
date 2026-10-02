from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = (
    ROOT / ".autodev" / "improvement" / "proof" / "final"
)
CAMPAIGN_EVIDENCE_PATH = (
    ROOT
    / ".autodev"
    / "campaign-evidence"
    / "v1.9-continuous-improvement-proof-001.json"
)
PROJECT_STATE_PATH = ROOT / ".autodev" / "state.json"
ACCEPTANCE_PATH = ROOT / "ACCEPTANCE.md"

PROOF_ID = "v1.9-continuous-improvement-proof-001"
SOURCE_RELEASE_CANDIDATE_ID = "release-a4cd075b270b6ad434ae2602"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
TARGET_REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
TARGET_PULL_REQUEST = 23
TARGET_HEAD_SHA = "4057ebca5c4405573ae73300d03b208edf95ca62"
TARGET_MERGE_SHA = "fa4f4b3a87f78d2bea596177811247072bca37ce"
TARGET_CI_RUN_ID = 37003361924
RUNTIME_VERIFICATION_ID = (
    "rv-fa4f4b3a87f78d2bea596177811247072bca37ce"
)
FINALIZER_RUN_ID = 37006828173
FINALIZER_ARTIFACT_ID = 11225659537
LINEAGE_RETIREMENT_ID = (
    "improvement-retire-336135bb9001804ae286272e"
)
LINEAGE_RETIREMENT_FINGERPRINT = (
    "eceba0d4aad0a68b6d53e74792d6ee44d20e3d0568ec558234d4973833b806d1"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_finalizer():
    path = (
        ROOT
        / ".github"
        / "trusted"
        / "v1_9_improvement_finalize.py"
    )
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_9_improvement_graduation_audit",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.9 improvement finalizer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frozen_api(external: dict[str, Any]):
    target = external.get("target")
    if not isinstance(target, dict):
        raise ValueError("v1.9 external target provenance is invalid")

    def api_get(url: str):
        if url.endswith(f"/pulls/{TARGET_PULL_REQUEST}"):
            return {
                "number": target["pull_request"],
                "state": "closed",
                "merged": True,
                "merged_at": target["merged_at"],
                "merge_commit_sha": target["merge_sha"],
                "title": target["title"],
                "head": {"sha": target["head_sha"]},
                "base": {
                    "sha": target["base_sha"],
                    "ref": "main",
                },
            }
        if url.endswith(
            f"/pulls/{TARGET_PULL_REQUEST}/files?per_page=100"
        ):
            return [
                {
                    "filename": path,
                    "status": "modified",
                }
                for path in target["changed_paths"]
            ]
        if url.endswith(
            f"/actions/runs/{TARGET_CI_RUN_ID}"
        ):
            return {
                "id": target["target_ci_run_id"],
                "name": target["target_ci_workflow_name"],
                "event": target["target_ci_event"],
                "status": "completed",
                "conclusion": target["target_ci_conclusion"],
                "head_sha": target["target_ci_head_sha"],
                "head_branch": target[
                    "target_ci_head_branch"
                ],
                "run_attempt": 1,
                "created_at": target["target_ci_created_at"],
                "updated_at": target["target_ci_updated_at"],
            }
        raise AssertionError(f"unexpected frozen GitHub API URL: {url}")

    return api_get


def _assert_equal(
    actual: object,
    expected: object,
    *,
    label: str,
) -> None:
    if actual != expected:
        raise ValueError(
            f"v1.9 Graduation evidence drift: {label}"
        )


def audit() -> dict[str, Any]:
    finalizer = _load_finalizer()

    frozen = {
        "terminal_state": _load_json(
            FINAL_DIR / "terminal-state.json"
        ),
        "terminal_campaign": _load_json(
            FINAL_DIR / "terminal-campaign.json"
        ),
        "remote_execution": _load_json(
            FINAL_DIR / "remote-execution.json"
        ),
        "runtime_contract": _load_json(
            FINAL_DIR / "runtime-contract.json"
        ),
        "runtime_receipt": _load_json(
            FINAL_DIR / "runtime-receipt.json"
        ),
        "runtime_report": _load_json(
            FINAL_DIR / "runtime-report.json"
        ),
        "runtime_provenance": _load_json(
            FINAL_DIR / "runtime-provenance.json"
        ),
        "external_provenance": _load_json(
            FINAL_DIR / "external-provenance.json"
        ),
    }

    bundle = finalizer.build_final_proof(
        api_get=_frozen_api(frozen["external_provenance"]),
        terminal_state_payload=frozen["terminal_state"],
        campaign_payload=frozen["terminal_campaign"],
        remote_payload=frozen["remote_execution"],
        runtime_contract_payload=frozen["runtime_contract"],
        runtime_receipt_payload=frozen["runtime_receipt"],
        runtime_report_payload=frozen["runtime_report"],
        runtime_provenance_payload=frozen[
            "runtime_provenance"
        ],
    )

    final_mapping = {
        "terminal-state.json": "terminal_state",
        "terminal-campaign.json": "terminal_campaign",
        "remote-execution.json": "remote_execution",
        "runtime-contract.json": "runtime_contract",
        "runtime-receipt.json": "runtime_receipt",
        "runtime-report.json": "runtime_report",
        "runtime-provenance.json": "runtime_provenance",
        "external-provenance.json": "external_provenance",
        "lineage-retirement.json": "lineage_retirement",
        "backlog-retirement.json": "backlog_retirement",
        "post-resolution.json": "post_resolution",
        "post-backlog-resolution.json": (
            "post_backlog_resolution"
        ),
        "post-backlog-selection.json": (
            "post_backlog_selection"
        ),
        "mission-control.json": "mission_control",
        "campaign-evidence.json": "campaign_evidence",
    }
    for filename, key in final_mapping.items():
        _assert_equal(
            _load_json(FINAL_DIR / filename),
            bundle[key],
            label=filename,
        )

    evidence = bundle["campaign_evidence"]
    if (
        evidence.get("schema_version") != 1
        or evidence.get("version") != "v1.9"
        or evidence.get("proof_id") != PROOF_ID
        or evidence.get("target_repository")
        != TARGET_REPOSITORY
        or evidence.get("source_release_candidate_id")
        != SOURCE_RELEASE_CANDIDATE_ID
        or evidence.get("source_release_sha") != SOURCE_SHA
        or evidence.get("closed_loop_verified") is not True
        or evidence.get("human_authored_per_task_work_items")
        is not False
        or evidence.get(
            "manual_campaign_progress_after_goal_submission"
        )
        is not False
        or evidence.get("execution_provenance_clean")
        is not True
    ):
        raise ValueError("v1.9 campaign evidence identity drift")

    execution = evidence.get("execution")
    runtime = evidence.get("runtime_verification")
    closure = evidence.get("closure")
    planning = evidence.get("planning")
    if not all(
        isinstance(value, dict)
        for value in (execution, runtime, closure, planning)
    ):
        raise ValueError("v1.9 campaign evidence sections invalid")
    if (
        execution.get("pull_request")
        != TARGET_PULL_REQUEST
        or execution.get("head_sha") != TARGET_HEAD_SHA
        or execution.get("merge_sha") != TARGET_MERGE_SHA
        or execution.get("changed_paths")
        != ["tests/test_models.py"]
        or execution.get("target_ci_run_id")
        != TARGET_CI_RUN_ID
    ):
        raise ValueError("v1.9 target execution evidence drift")
    if (
        planning.get("tests_only") is not True
        or planning.get("max_tasks") != 1
    ):
        raise ValueError("v1.9 PlanningGoal scope drift")
    if (
        runtime.get("verification_id")
        != RUNTIME_VERIFICATION_ID
        or runtime.get("workflow_run_id") != 37003477881
        or runtime.get("remote_monitor_workflow_run_id")
        != 37003386651
        or runtime.get("disposition") != "VERIFIED"
    ):
        raise ValueError("v1.9 Runtime Verification evidence drift")
    if (
        closure.get("lineage_retirement_id")
        != LINEAGE_RETIREMENT_ID
        or closure.get("lineage_retirement_fingerprint")
        != LINEAGE_RETIREMENT_FINGERPRINT
        or closure.get("cycle_state") != "VERIFIED_RETIRED"
        or closure.get("current_signal_count") != 0
        or closure.get("retired_signal_count") != 1
        or closure.get("lineage_retirement_count") != 1
    ):
        raise ValueError("v1.9 closed-loop retirement drift")

    post_resolution = bundle["post_resolution"]
    if (
        post_resolution.get("current_signal_ids") != []
        or LINEAGE_RETIREMENT_FINGERPRINT
        not in post_resolution.get("retirement_fingerprints", [])
    ):
        raise ValueError(
            "v1.9 retired signal remained eligible"
        )
    post_selection = bundle["post_backlog_selection"]
    if (
        post_selection.get("selected_candidate_id") is not None
        or post_selection.get("eligible_candidate_ids") != []
    ):
        raise ValueError(
            "v1.9 retired Backlog candidate remained selectable"
        )
    mission = bundle["mission_control"]
    if (
        mission.get("cycle_state") != "VERIFIED_RETIRED"
        or mission.get("current_count") != 0
        or mission.get("retired_count") != 1
        or mission.get("lineage_retirement_count") != 1
        or mission.get("latest_retirement_id")
        != LINEAGE_RETIREMENT_ID
    ):
        raise ValueError(
            "v1.9 final Mission Control projection drift"
        )

    _assert_equal(
        _load_json(CAMPAIGN_EVIDENCE_PATH),
        evidence,
        label="graduation campaign evidence",
    )

    provenance = _load_json(
        FINAL_DIR / "finalization-provenance.json"
    )
    if (
        provenance.get("schema_version") != 1
        or provenance.get("proof_id") != PROOF_ID
        or provenance.get("workflow_run_id")
        != FINALIZER_RUN_ID
        or provenance.get("finalizer_state")
        != "EVIDENCE_FROZEN"
        or provenance.get("target_pull_request")
        != TARGET_PULL_REQUEST
        or provenance.get("target_merge_sha")
        != TARGET_MERGE_SHA
        or provenance.get("runtime_workflow_run_id")
        != 37003477881
        or provenance.get("lineage_retirement_id")
        != LINEAGE_RETIREMENT_ID
        or provenance.get(
            "external_write_after_successor_merge"
        )
        is not False
    ):
        raise ValueError("v1.9 finalizer provenance drift")

    project_state = _load_json(PROJECT_STATE_PATH)
    metadata = project_state.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("project state metadata is invalid")
    expected_metadata = {
        "v1_9_graduated": True,
        "v1_9_graduation_evidence": str(
            CAMPAIGN_EVIDENCE_PATH.relative_to(ROOT)
        ),
        "v1_9_proof_001_verified": True,
        "v1_9_proof_target_pull_request": TARGET_PULL_REQUEST,
        "v1_9_proof_target_final_sha": TARGET_MERGE_SHA,
        "v1_9_runtime_verification_id": (
            RUNTIME_VERIFICATION_ID
        ),
        "v1_9_lineage_retirement_id": (
            LINEAGE_RETIREMENT_ID
        ),
        "v1_9_lineage_retirement_fingerprint": (
            LINEAGE_RETIREMENT_FINGERPRINT
        ),
        "v1_9_finalizer_workflow_run_id": (
            FINALIZER_RUN_ID
        ),
        "v1_9_finalizer_artifact_id": (
            FINALIZER_ARTIFACT_ID
        ),
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            raise ValueError(
                f"v1.9 project state metadata drift: {key}"
            )

    stable_metadata = {
        "milestone": "v1.9-graduated",
        "next_required_human_action": None,
        "next_system_action": None,
        "queue_exhausted": True,
    }
    for key, expected in stable_metadata.items():
        if metadata.get(key) != expected:
            raise ValueError(
                f"v1.9 stable project state drift: {key}"
            )
    if (
        project_state.get("status") != "READY"
        or project_state.get("current_task_id") is not None
        or project_state.get("failed_task_ids") != []
    ):
        raise ValueError(
            "v1.9 graduated ProjectState is not stable READY"
        )

    graduated_at = metadata.get("v1_9_graduated_at")
    if not isinstance(graduated_at, str) or not graduated_at:
        raise ValueError(
            "v1.9 graduation timestamp is missing"
        )

    acceptance = ACCEPTANCE_PATH.read_text(
        encoding="utf-8"
    )
    required_checks = (
        "- [x] A real external-repository proof demonstrates verified release -> trusted improvement signal -> backlog/PlanningGoal -> trusted execution -> verified outcome without manual per-task authoring.",
        "- [x] A dedicated v1.9 Graduation audit reconstructs the Continuous Improvement proof end to end.",
    )
    for check in required_checks:
        if check not in acceptance:
            raise ValueError(
                "v1.9 Acceptance graduation check is incomplete"
            )

    return {
        "schema_version": 1,
        "version": "v1.9",
        "proof_id": PROOF_ID,
        "source_release_candidate_id": (
            SOURCE_RELEASE_CANDIDATE_ID
        ),
        "source_sha": SOURCE_SHA,
        "target_pull_request": TARGET_PULL_REQUEST,
        "target_merge_sha": TARGET_MERGE_SHA,
        "target_ci_run_id": TARGET_CI_RUN_ID,
        "runtime_verification_id": (
            RUNTIME_VERIFICATION_ID
        ),
        "lineage_retirement_id": (
            LINEAGE_RETIREMENT_ID
        ),
        "closed_loop_verified": True,
        "graduated": True,
        "human_authored_per_task_work_items": False,
    }


def main() -> int:
    try:
        result = audit()
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        message = (
            str(exc).splitlines()[0].strip()
            if str(exc).strip()
            else type(exc).__name__
        )
        print(
            json.dumps(
                {"ok": False, "error": message[:256]},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
