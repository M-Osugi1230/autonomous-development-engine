from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from jules_client import JulesClient, JulesError, JulesQuota

OUT = Path(".autodev/runtime/jules-plan-probe.json")

STRUCTURED_REQUEST = """
Do not approve or execute the plan. Do not modify files.
Reply with exactly one JSON object and no markdown fences.
Use this exact schema:
{
  "schema_version": 1,
  "goal": "Add a small pure helper that summarizes two non-empty strings into a deterministic dictionary, plus focused stdlib tests.",
  "tasks": [
    {
      "key": "short-local-key",
      "title": "short task title",
      "outcome": "bounded outcome",
      "depends_on": [],
      "allowed_paths": ["relative/path.py"],
      "acceptance": ["deterministic acceptance check"],
      "human_only": false,
      "human_reason": null
    }
  ],
  "human_boundaries": [
    "destructive or irreversible operation",
    "credential or secret access",
    "externally consequential side effect"
  ]
}
Use 1-3 tasks. Dependencies must reference earlier task keys. Keep paths limited to src/ade/ and tests/.
""".strip()


def _write(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _session_id(session: dict[str, Any]) -> str | None:
    value = session.get("id")
    if isinstance(value, str) and value.strip():
        return value
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        suffix = name.removeprefix("sessions/")
        if suffix and "/" not in suffix:
            return suffix
    return None


def _list_activities(client: JulesClient, session_id: str) -> list[dict[str, Any]]:
    last_error: JulesError | None = None
    for attempt in range(1, 7):
        try:
            payload = client._request(
                "GET",
                f"sessions/{session_id}/activities",
                query={"pageSize": 100},
            )
            activities = payload.get("activities", [])
            if not isinstance(activities, list):
                raise JulesError("activities response has invalid shape")
            return [item for item in activities if isinstance(item, dict)]
        except JulesError as exc:
            last_error = exc
            if "HTTP 404:" not in str(exc) or attempt >= 6:
                raise
            time.sleep(min(attempt * 2, 10))
    assert last_error is not None
    raise last_error


def _agent_messages(activities: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for activity in activities:
        event = activity.get("agentMessaged")
        if not isinstance(event, dict):
            continue
        message = event.get("agentMessage")
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    return messages


def _extract_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def main() -> int:
    client = JulesClient()
    try:
        sessions = client.list_sessions(page_size=100, max_pages=2)
        candidates: list[tuple[str, dict[str, Any]]] = []
        for session in sessions:
            title = session.get("title")
            state = session.get("state")
            sid = _session_id(session)
            if (
                isinstance(title, str)
                and "planner probe" in title.casefold()
                and state == "AWAITING_PLAN_APPROVAL"
                and sid is not None
            ):
                candidates.append((str(session.get("createTime", "")), {"sid": sid, "session": session}))
        if not candidates:
            _write({"schema_version": 1, "ok": False, "reason": "no-awaiting-plan-session"})
            print('{"ok":false,"reason":"no-awaiting-plan-session"}')
            return 2

        candidates.sort(key=lambda item: item[0])
        target = candidates[-1][1]
        sid = target["sid"]

        before = _list_activities(client, sid)
        before_messages = _agent_messages(before)
        client._request(
            "POST",
            f"sessions/{sid}:sendMessage",
            payload={"prompt": STRUCTURED_REQUEST},
        )

        proposal: dict[str, Any] | None = None
        new_message: str | None = None
        final_state: str | None = None
        for _ in range(24):
            time.sleep(5)
            current = client.get_session(sid)
            state = current.get("state")
            final_state = state if isinstance(state, str) else None
            activities = _list_activities(client, sid)
            messages = _agent_messages(activities)
            for message in messages[len(before_messages):]:
                parsed = _extract_json_object(message)
                if parsed is not None:
                    proposal = parsed
                    new_message = message
                    break
            if proposal is not None:
                break

        payload = {
            "schema_version": 1,
            "ok": proposal is not None,
            "mode": "structured-proposal-from-existing-plan-session",
            "state": final_state,
            "session_remained_unapproved": final_state != "IN_PROGRESS",
            "structured_proposal": proposal,
            "agent_message_present": new_message is not None,
        }
        _write(payload)
        print(json.dumps({
            "ok": proposal is not None,
            "state": final_state,
            "session_remained_unapproved": final_state != "IN_PROGRESS",
            "structured_proposal_present": proposal is not None,
        }, sort_keys=True))
        return 0 if proposal is not None and final_state != "IN_PROGRESS" else 3
    except JulesQuota as exc:
        _write({"schema_version": 1, "ok": False, "state": "PAUSED_QUOTA", "error": str(exc)[:256]})
        print("Jules structured planner probe hit provider quota")
        return 20
    except JulesError as exc:
        _write({"schema_version": 1, "ok": False, "state": "PROVIDER_ERROR", "error": str(exc)[:256]})
        print(f"Jules structured planner probe error: {str(exc)[:256]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
