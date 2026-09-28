from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jules_client import JulesClient, JulesError

OUT = Path(".autodev/runtime/v1-2-session-diagnostic.json")
TITLE = "ADE planner: v1.2-external-goal-proof-001"


def _session_id(session: dict[str, Any]) -> str:
    value = session.get("id")
    if isinstance(value, str) and value.strip():
        return value
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        return name.removeprefix("sessions/")
    raise RuntimeError("session id missing")


def _plan_steps(activities: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for activity in activities:
        event = activity.get("planGenerated")
        if not isinstance(event, dict):
            continue
        plan = event.get("plan")
        if not isinstance(plan, dict):
            continue
        steps = plan.get("steps")
        if not isinstance(steps, list):
            continue
        for raw in steps:
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            description = raw.get("description")
            if isinstance(title, str) and title.strip():
                result.append({
                    "title": title.strip()[:1000],
                    "description": description.strip()[:4000] if isinstance(description, str) else "",
                })
    return result


def main() -> int:
    client = JulesClient()
    matches = [
        item for item in client.list_sessions(page_size=100, max_pages=10)
        if item.get("title") == TITLE
    ]
    matches.sort(key=lambda item: str(item.get("createTime", "")), reverse=True)
    output: list[dict[str, Any]] = []
    for item in matches[:5]:
        sid = _session_id(item)
        current = client.get_session(sid)
        try:
            activities = client.list_activities(sid, page_size=100)
            activity_error = None
        except JulesError as exc:
            activities = []
            activity_error = str(exc)[:256]
        output.append({
            "create_time": item.get("createTime"),
            "state": current.get("state"),
            "activity_count": len(activities),
            "plan_steps": _plan_steps(activities),
            "activity_error": activity_error,
        })

    payload = {
        "schema_version": 1,
        "title": TITLE,
        "matching_sessions": len(matches),
        "sessions": output,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "matching_sessions": len(matches),
        "sessions": [
            {
                "state": item["state"],
                "activity_count": item["activity_count"],
                "plan_step_count": len(item["plan_steps"]),
                "activity_error": item["activity_error"],
            }
            for item in output
        ],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
