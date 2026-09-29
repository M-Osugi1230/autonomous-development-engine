from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import autonomous_planner_cycle as cycle
from ade.autonomous_planner import PlannerProposal, validate_planner_proposal
from ade.models import ProjectState, ProjectStatus
from ade.planning_activation import PlanningGoalRequest, build_planning_activation
from ade.repository_intelligence import build_repository_snapshot, planner_repository_context


BOUNDARIES = [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect",
]


class FakeGitHub:
    def __init__(self):
        self.writes = []
        self.dispatches = []

    def upsert_json_file(self, path, payload, *, message, branch="main"):
        self.writes.append((path, payload, message, branch))

    def dispatch(self, event_type, payload=None):
        self.dispatches.append((event_type, payload or {}))

    def get_branch_head_sha(self, repository, *, branch="main"):
        assert repository == "example/target"
        assert branch == "main"
        return "a" * 40

    def list_tree_paths(self, repository, *, tree_sha, max_entries=5000):
        assert repository == "example/target"
        assert tree_sha == "a" * 40
        assert max_entries == 5000
        return [
            "README.md",
            "pyproject.toml",
            ".github/workflows/ci.yml",
            "src/helper.py",
            "tests/test_helper.py",
        ]


def main() -> int:
    request = PlanningGoalRequest(
        request_id="planner-cycle-proof",
        campaign_id="planner-cycle-campaign",
        id_prefix="pcp",
        goal="Add a safe helper and focused tests.",
        target_repository="example/target",
        base_branch="main",
        allowed_path_prefixes=("src", "tests"),
        min_tasks=2,
        max_tasks=4,
    )
    proposal = {
        "schema_version": 1,
        "goal": request.goal,
        "tasks": [
            {
                "key": "helper",
                "title": "Add helper",
                "outcome": "Add a deterministic helper.",
                "depends_on": [],
                "allowed_paths": ["src/helper.py"],
                "acceptance": ["helper is deterministic"],
                "human_only": False,
                "human_reason": None,
            },
            {
                "key": "tests",
                "title": "Test helper",
                "outcome": "Add focused tests.",
                "depends_on": ["helper"],
                "allowed_paths": ["tests/test_helper.py"],
                "acceptance": ["focused tests pass"],
                "human_only": False,
                "human_reason": None,
            },
        ],
        "human_boundaries": BOUNDARIES,
    }
    validated = validate_planner_proposal(
        high_level_goal=request.goal,
        proposal_payload=proposal,
        policy=request.planner_policy(),
        id_prefix=request.id_prefix,
    )
    previous = ProjectState(
        schema_version=1,
        project_id="ade",
        status=ProjectStatus.READY,
        iteration=52,
        current_task_id=None,
        completed_task_ids=["previous-task"],
        failed_task_ids=[],
        provider="jules",
        updated_at=None,
        metadata={},
    )
    bundle = build_planning_activation(
        request=request,
        validated=validated,
        previous_state=previous,
    )
    result = SimpleNamespace(raw_proposal=proposal)
    provider = SimpleNamespace(
        last_plan_steps=(
            {"title": "Add helper", "description": "safe plan detail"},
            {"title": "Test helper", "description": "safe test detail"},
        ),
        last_observed_state="AWAITING_PLAN_APPROVAL",
    )
    gh = FakeGitHub()
    snapshot, repository_context = cycle._collect_repository_intelligence(
        gh,
        request,
    )
    assert snapshot.repository == "example/target"
    assert snapshot.source_sha == "a" * 40
    assert repository_context.payload["known_files_within_trusted_roots"] == [
        "src/helper.py",
        "tests/test_helper.py",
    ]

    old_write = cycle._write_result
    cycle._write_result = lambda payload: None
    try:
        cycle._persist_activation(
            gh,
            request=request,
            result=result,
            bundle=bundle,
            provider=provider,
            snapshot=snapshot,
            repository_context=repository_context,
            attempt=1,
        )
    finally:
        cycle._write_result = old_write

    paths = [item[0] for item in gh.writes]
    assert paths[-1] == ".autodev/accepted-plan.json"
    assert paths[:4] == [
        ".autodev/campaign.json",
        ".autodev/task-graph.json",
        ".autodev/cycle-task.json",
        ".autodev/state.json",
    ]
    assert ".autodev/planner-evidence/planner-cycle-proof.json" in paths
    assert ".autodev/repository-intelligence/planner-cycle-proof.json" in paths
    assert ".autodev/runtime/planning-status.json" in paths

    evidence = next(payload for path, payload, _, _ in gh.writes if path.endswith("planner-cycle-proof.json"))
    serialized = json.dumps(evidence, sort_keys=True)
    assert "session_id" not in serialized
    assert "provider_session" not in serialized
    assert evidence["plan_approved"] is False
    assert evidence["planning_only"] is True
    assert evidence["repository_snapshot_fingerprint"] == snapshot.fingerprint()
    assert evidence["repository_context_fingerprint"] == repository_context.fingerprint
    intelligence = next(
        payload
        for path, payload, _, _ in gh.writes
        if path.endswith("repository-intelligence/planner-cycle-proof.json")
    )
    assert intelligence["snapshot_fingerprint"] == snapshot.fingerprint()
    assert intelligence["planner_context_fingerprint"] == repository_context.fingerprint
    prepared_state = gh.writes[3][1]
    metadata = prepared_state["metadata"]
    assert metadata["repository_intelligence_snapshot_fingerprint"] == snapshot.fingerprint()
    assert metadata["repository_intelligence_context_fingerprint"] == repository_context.fingerprint
    assert metadata["repository_intelligence_source_sha"] == snapshot.source_sha

    accepted = gh.writes[-1][1]
    assert accepted["status"] == "ACCEPTED"
    assert accepted["fingerprint"] == bundle.accepted_plan.fingerprint
    assert gh.dispatches == [
        (
            "ade_zero_touch_start",
            {
                "task_id": bundle.cycle_task.task_id,
                "campaign_id": bundle.campaign.campaign_id,
                "request_id": request.request_id,
                "source": "autonomous-planner",
            },
        )
    ]

    retry_gh = FakeGitHub()
    cycle._arm_capacity_retry(retry_gh, request)
    assert retry_gh.dispatches == [
        (
            "ade_planner_retry_arm",
            {
                "request_id": request.request_id,
                "request_fingerprint": request.fingerprint(),
                "source": "autonomous-planner-capacity-pause",
            },
        )
    ]

    print(json.dumps({
        "ok": True,
        "canonical_state_before_trigger": True,
        "accepted_plan_written_last": True,
        "secret_free_provider_identity": True,
        "planning_only_evidence": True,
        "fingerprint_reconciled": True,
        "trusted_task_count_bounds": True,
        "explicit_zero_touch_dispatch": True,
        "capacity_retry_arm": True,
        "repository_intelligence_snapshot": True,
        "repository_intelligence_evidence": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
