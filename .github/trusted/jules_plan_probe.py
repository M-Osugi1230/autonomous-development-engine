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
        return [_safe_shape(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:16000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)[:1000]


def _write(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _resource_suffix(session: dict[str, Any]) -> str | None:
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        suffix = name.removeprefix("sessions/")
        if suffix and "/" not in suffix:
            return suffix
    return None


def _id_value(session: dict[str, Any]) -> str | None:
    value = session.get("id")
    return value if isinstance(value, str) and value.strip() else None


def _try_activities(client: JulesClient, identifier: str) -> tuple[bool, dict[str, Any] | str]:
    try:
        payload = client._request("GET", f"sessions/{identifier}/activities", query={"pageSize": 100})
        return True, payload
    except JulesError as exc:
        return False, str(exc)[:256]


def main() -> int:
    client = JulesClient()
    try:
        sessions = client.list_sessions(page_size=100, max_pages=2)
        diagnostics: list[dict[str, Any]] = []
        any_success = False

        for session in sessions:
            title = session.get("title")
            if not isinstance(title, str) or "planner probe" not in title.casefold():
                continue

            sid = _id_value(session)
            suffix = _resource_suffix(session)
            record: dict[str, Any] = {
                "title": title,
                "state": session.get("state"),
                "id_present": sid is not None,
                "resource_name_present": suffix is not None,
                "id_matches_resource_suffix": sid is not None and suffix is not None and sid == suffix,
            }

            if sid is not None:
                ok, result = _try_activities(client, sid)
                record["activities_by_id_ok"] = ok
                if ok:
                    any_success = True
                    record["activities_by_id"] = _safe_shape(result)
                else:
                    record["activities_by_id_error"] = result

            if suffix is not None:
                ok, result = _try_activities(client, suffix)
                record["activities_by_resource_name_ok"] = ok
                if ok:
                    any_success = True
                    record["activities_by_resource_name"] = _safe_shape(result)
                else:
                    record["activities_by_resource_name_error"] = result

            diagnostics.append(record)

        payload = {
            "schema_version": 1,
            "ok": any_success,
            "mode": "diagnose-activity-parent-identifier",
            "matching_session_count": len(diagnostics),
            "sessions": diagnostics[-5:],
        }
        _write(payload)
        print(json.dumps({
            "ok": any_success,
            "matching_session_count": len(diagnostics),
            "resource_name_differs_from_id": any(
                item.get("id_present")
                and item.get("resource_name_present")
                and not item.get("id_matches_resource_suffix")
                for item in diagnostics
            ),
            "activities_by_id_any_success": any(item.get("activities_by_id_ok") for item in diagnostics),
            "activities_by_resource_name_any_success": any(item.get("activities_by_resource_name_ok") for item in diagnostics),
        }, sort_keys=True))
        return 0 if any_success else 2
    except JulesQuota as exc:
        _write({"schema_version": 1, "ok": False, "state": "PAUSED_QUOTA", "error": str(exc)[:256]})
        print("Jules activity diagnostic hit provider quota")
        return 20
    except JulesError as exc:
        _write({"schema_version": 1, "ok": False, "state": "PROVIDER_ERROR", "error": str(exc)[:256]})
        print(f"Jules activity diagnostic error: {str(exc)[:256]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
