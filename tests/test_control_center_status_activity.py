from datetime import datetime, timedelta, timezone

from api.status import _activity_state


def _iso(hours_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_terminal_and_wait_states_are_explicit() -> None:
    assert _activity_state(
        "COMPLETED", last_state_change_at=None, workflow_status=None, next_system_action=None
    ) == "COMPLETED"
    assert _activity_state(
        "FAILED", last_state_change_at=None, workflow_status=None, next_system_action=None
    ) == "STOPPED"
    assert _activity_state(
        "HUMAN_WAIT", last_state_change_at=None, workflow_status=None, next_system_action=None
    ) == "BLOCKED"
    assert _activity_state(
        "READY", last_state_change_at=None, workflow_status=None, next_system_action=None
    ) == "IDLE"


def test_active_workflow_wins_over_old_state_timestamp() -> None:
    assert _activity_state(
        "RUNNING",
        last_state_change_at=_iso(24),
        workflow_status="in_progress",
        next_system_action="monitor-provider-session",
    ) == "ACTIVE"


def test_recent_provider_monitor_is_monitoring() -> None:
    assert _activity_state(
        "RUNNING",
        last_state_change_at=_iso(1),
        workflow_status="completed",
        next_system_action="monitor-provider-session",
    ) == "MONITORING"


def test_running_project_without_state_change_for_six_hours_is_stale() -> None:
    assert _activity_state(
        "RUNNING",
        last_state_change_at=_iso(7),
        workflow_status="completed",
        next_system_action="monitor-provider-session",
    ) == "STALE"
