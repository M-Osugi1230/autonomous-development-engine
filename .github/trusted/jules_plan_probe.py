from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ade.providers.jules import JulesProvider
from ade.providers.base import ProviderError, ProviderQuotaError

OUT = Path(".autodev/runtime/jules-plan-probe.json")


def _session_id(session: dict[str, Any]) -> str:
    value = session.get("id")
    if isinstance(value, str) and value.strip():
        return value
    name = session.get("name")
    if isinstance(name, str) and name.startswith("sessions/"):
        value = name.removeprefix("sessions/")
        if value:
            return value
    raise RuntimeError("Jules session did not return an id")


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
        return value[:12000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return repr(value)[:1000]


def _write(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    owner = os.environ.get("ADE_GITHUB_OWNER", "M-Osugi1230")
    repo = os.environ.get("ADE_GITHUB_REPO", "autonomous-development-engine")
    provider = JulesProvider()
    source = provider.find_github_source(owner, repo)
    if source is None:
        raise RuntimeError(f"{owner}/{repo} is not visible to Jules")
    source_name = source.get("name")
    if not isinstance(source_name, str) or not source_name.strip():
        raise RuntimeError("Jules source is missing a resource name")

    prompt = """
Analyze this repository and create an implementation plan only. Do not modify files and do not create a pull request.
Goal: Add a small pure helper that summarizes two non-empty strings into a deterministic dictionary, plus focused stdlib tests.
The final plan should describe 1-3 bounded tasks, dependencies, proposed allowed paths, and deterministic acceptance checks.
If possible, include one JSON object with fields: schema_version, goal, tasks, human_boundaries.
Each task should include key, title, outcome, depends_on, allowed_paths, acceptance, human_only, human_reason.
Do not request secrets, deployment, external side effects, destructive changes, workflow changes, or .autodev changes.
""".strip()

    stage = "create_session"
    try:
        session = provider.create_session(
            prompt=prompt,
            source=source_name,
            starting_branch="main",
            title="ADE v1.2 planner probe",
            auto_create_pr=False,
            require_plan_approval=True,
        )
        sid = _session_id(session)
        terminal_state = "UNKNOWN"
        observed_states: list[str] = []
        last_session: dict[str, Any] = {}

        for _ in range(60):
            stage = "get_session"
            current = provider.get_session(sid)
            last_session = current
            state = current.get("state")
            if isinstance(state, str):
                terminal_state = state
                if not observed_states or observed_states[-1] != state:
                    observed_states.append(state)
            if terminal_state in {
                "AWAITING_PLAN_APPROVAL",
                "AWAITING_USER_FEEDBACK",
                "COMPLETED",
                "FAILED",
                "PAUSED",
            }:
                break
            time.sleep(5)

        _write(
            {
                "schema_version": 1,
                "ok": terminal_state not in {"FAILED"},
                "session_present": True,
                "state": terminal_state,
                "observed_states": observed_states,
                "session": _safe_shape(last_session),
            }
        )
        print(json.dumps({
            "ok": terminal_state not in {"FAILED"},
            "state": terminal_state,
            "observed_states": observed_states,
        }, sort_keys=True))
        return 0 if terminal_state not in {"FAILED"} else 1
    except ProviderQuotaError as exc:
        _write({"schema_version": 1, "ok": False, "state": "PAUSED_QUOTA", "stage": stage, "error": str(exc)[:256]})
        print("Jules planner probe hit provider quota")
        return 20
    except ProviderError as exc:
        _write({"schema_version": 1, "ok": False, "state": "PROVIDER_ERROR", "stage": stage, "error": str(exc)[:256]})
        print(f"Jules planner probe provider error at {stage}: {str(exc)[:256]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
