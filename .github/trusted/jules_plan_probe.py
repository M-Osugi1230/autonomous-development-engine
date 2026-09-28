from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jules_client import JulesClient, JulesError, JulesQuota

OUT = Path(".autodev/runtime/jules-plan-probe.json")


def _safe_shape(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[DEPTH-LIMIT]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).casefold()
            if any(marker in lowered for marker in ("token", "secret", "credential", "authorization")):
                result[str(key)] = "[REDACTED]"
                continue
            if lowered in {"id", "sessionid", "session_id", "url", "uri", "name"}:
                if isinstance(item, str) and ("session" in item.casefold() or "http" in item.casefold()):
                    result[str(key)] = "[REDACTED]"
                    continue
            result[str(key)] = _safe_shape(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [_safe_shape(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return value[:16000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)[:1000]


def _session_id(session: dict[str, Any]) -> str | None:
    value = session.get("id")
    if isinstance(value, str) and value.strip():
        return value
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        value = name.removeprefix("sessions/")
        if value:
            return value
    return None


def _write(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    client = JulesClient()
    try:
        sessions = client.list_sessions(page_size=100, max_pages=2)
        matches: list[dict[str, Any]] = []
        fallback: list[dict[str, Any]] = []
        for session in sessions:
            title = session.get("title")
            safe_summary = {
                "title": title if isinstance(title, str) else None,
                "state": session.get("state"),
                "createTime": session.get("createTime"),
            }
            fallback.append(safe_summary)
            if isinstance(title, str) and "planner probe" in title.casefold():
                sid = _session_id(session)
                if sid is None:
                    continue
                current = client.get_session(sid)
                matches.append(_safe_shape(current))

        payload = {
            "schema_version": 1,
            "ok": bool(matches),
            "mode": "recover-existing-plan-sessions",
            "matching_sessions": matches[-5:],
            "recent_session_summaries": _safe_shape(fallback[-20:]),
        }
        _write(payload)
        print(json.dumps({
            "ok": bool(matches),
            "matching_sessions": len(matches),
            "total_sessions": len(sessions),
        }, sort_keys=True))
        return 0 if matches else 2
    except JulesQuota as exc:
        _write({"schema_version": 1, "ok": False, "state": "PAUSED_QUOTA", "error": str(exc)[:256]})
        print("Jules session recovery probe hit provider quota")
        return 20
    except JulesError as exc:
        _write({"schema_version": 1, "ok": False, "state": "PROVIDER_ERROR", "error": str(exc)[:256]})
        print(f"Jules session recovery probe error: {str(exc)[:256]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
