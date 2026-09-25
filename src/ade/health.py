from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ProjectState


def health_snapshot(state: ProjectState) -> dict[str, object]:
    """Return a dictionary representing a health snapshot of the given project state."""
    state.validate()
    return {
        "project_id": state.project_id,
        "status": state.status.value if hasattr(state.status, "value") else str(state.status),
        "iteration": state.iteration,
        "current_task_id": state.current_task_id,
        "completed_tasks": len(state.completed_task_ids),
        "failed_tasks": len(state.failed_task_ids),
    }
