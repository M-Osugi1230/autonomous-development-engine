from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from jules_resume import decide_checkpoint_action


def run_probe() -> dict[str, object]:
    now = datetime(2026, 9, 26, 0, 30, tzinfo=UTC)
    due = (now - timedelta(minutes=5)).isoformat()
    future = (now + timedelta(minutes=5)).isoformat()

    due_without_session = {
        "task_id": "probe-task",
        "state": "PAUSED_QUOTA",
        "provider_session_id": None,
        "resume_after": due,
    }
    due_with_session = {
        "task_id": "probe-task",
        "state": "PAUSED_QUOTA",
        "provider_session_id": "probe-session",
        "resume_after": due,
    }
    not_due = {
        "task_id": "probe-task",
        "state": "PAUSED_QUOTA",
        "provider_session_id": "probe-session",
        "resume_after": future,
    }

    action_new, session_new = decide_checkpoint_action(due_without_session, now=now)
    action_monitor, session_monitor = decide_checkpoint_action(due_with_session, now=now)
    action_wait, session_wait = decide_checkpoint_action(not_due, now=now)

    if (action_new, session_new) != ("START_NEW", None):
        raise AssertionError("due quota checkpoint without session did not route to START_NEW")
    if (action_monitor, session_monitor) != ("MONITOR", "probe-session"):
        raise AssertionError("due quota checkpoint with session did not route to MONITOR")
    if (action_wait, session_wait) != ("WAIT", "probe-session"):
        raise AssertionError("future quota checkpoint did not remain WAIT")

    return {
        "ok": True,
        "due_without_session": action_new,
        "due_with_session": action_monitor,
        "not_due": action_wait,
    }


def main() -> int:
    try:
        result = run_probe()
    except Exception as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(json.dumps({"ok": False, "error": message[:256]}, sort_keys=True))
        return 1

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
