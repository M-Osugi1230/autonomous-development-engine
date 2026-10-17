from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

STATE_MUTATING_WORKFLOWS = (
    "ade-resume.yml",
    "autonomous-planner.yml",
    "jules-cycle.yml",
    "remote-pr-monitor.yml",
    "runtime-verification-retry.yml",
    "runtime-verification-watchdog.yml",
    "runtime-verification.yml",
    "zero-touch-start.yml",
)

MATRIX_STATE_MUTATING_WORKFLOWS = (
    "ade-resume.yml",
    "autonomous-planner.yml",
    "remote-pr-monitor.yml",
    "runtime-verification-watchdog.yml",
    "zero-touch-start.yml",
)


def _workflow(name: str) -> str:
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_state_mutating_workflows_share_project_state_concurrency_namespace() -> None:
    for name in STATE_MUTATING_WORKFLOWS:
        workflow = _workflow(name)
        assert "group: ade-project-state-${{" in workflow, name
        assert "cancel-in-progress: false" in workflow, name


def test_scheduled_matrix_jobs_lock_the_exact_control_ref() -> None:
    expected = "group: ade-project-state-${{ matrix.control_ref }}"
    for name in MATRIX_STATE_MUTATING_WORKFLOWS:
        assert expected in _workflow(name), name


def test_provider_cycle_uses_project_scoped_state_lock() -> None:
    workflow = _workflow("jules-cycle.yml")
    expected = (
        "group: ade-project-state-${{ "
        "github.event.client_payload.project_key || "
        "github.event.client_payload.control_ref || 'main' }}"
    )
    assert expected in workflow
