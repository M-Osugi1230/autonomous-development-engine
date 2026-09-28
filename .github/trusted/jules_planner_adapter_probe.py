from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ade.jules_planner import JulesPlannerConfig, JulesPlanningProvider
from jules_client import JulesClient


PROPOSAL = {
    "schema_version": 1,
    "goal": "Add helper",
    "tasks": [
        {
            "key": "helper",
            "title": "Add helper",
            "outcome": "Add pure helper",
            "depends_on": [],
            "allowed_paths": ["src/ade/helper.py"],
            "acceptance": ["helper is deterministic"],
            "human_only": False,
            "human_reason": None,
        }
    ],
    "human_boundaries": [
        "destructive or irreversible operation",
        "credential or secret access",
        "externally consequential side effect",
    ],
}


class RecordingJulesClient(JulesClient):
    def __init__(self):
        super().__init__(api_key="offline-test-key")
        self.requests = []
        self.phase = "initial"

    def _request(self, method, path, *, payload=None, query=None):
        self.requests.append((method, path, payload, query))
        if method == "POST" and path == "sessions":
            return {"id": "s1", "state": "QUEUED"}
        if method == "GET" and path == "sessions/s1":
            return {"id": "s1", "state": "AWAITING_PLAN_APPROVAL"}
        if method == "GET" and path == "sessions/s1/activities":
            if self.phase == "initial":
                return {
                    "activities": [
                        {
                            "planGenerated": {
                                "plan": {
                                    "steps": [
                                        {
                                            "title": "Add helper in `src/ade/helper.py`",
                                            "description": "Implement a pure helper at `src/ade/helper.py`",
                                        },
                                        {
                                            "title": "Add tests in `tests/test_helper.py`",
                                            "description": "Add focused tests at `tests/test_helper.py`",
                                        },
                                        {
                                            "title": "Complete pre commit steps",
                                            "description": "Verify and review the change",
                                        }
                                    ]
                                }
                            }
                        }
                    ]
                }
            return {
                "activities": [
                    {
                        "planGenerated": {
                            "plan": {
                                "steps": [
                                    {
                                        "title": "Add helper in `src/ade/helper.py`",
                                        "description": "Implement a pure helper at `src/ade/helper.py`",
                                    },
                                    {
                                        "title": "Add tests in `tests/test_helper.py`",
                                        "description": "Add focused tests at `tests/test_helper.py`",
                                    },
                                    {
                                        "title": "Complete pre commit steps",
                                        "description": "Verify and review the change",
                                    }
                                ]
                            }
                        }
                    },
                    {"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}},
                ]
            }
        if method == "POST" and path == "sessions/s1:sendMessage":
            self.phase = "after"
            return {}
        raise AssertionError((method, path, payload, query))


def main() -> int:
    client = RecordingJulesClient()
    provider = JulesPlanningProvider(
        client,
        JulesPlannerConfig(
            source_name="sources/github/example/repo",
            poll_interval_seconds=0.001,
            max_plan_polls=3,
            max_structured_polls=3,
            activity_404_retries=2,
            allowed_path_prefixes=("src/ade", "tests"),
        ),
        sleeper=lambda _: None,
    )
    result = provider.propose(
        "You are an untrusted planning component. Goal: Add helper. "
        "Trusted writable roots: src/ade, tests. Maximum tasks: 8"
    )
    assert result["schema_version"] == 1
    assert result["goal"] == "Add helper"
    assert len(result["tasks"]) == 2
    assert result["tasks"][0]["allowed_paths"] == ["src/ade/helper.py"]
    assert result["tasks"][1]["allowed_paths"] == ["tests/test_helper.py"]

    create = next(item for item in client.requests if item[0] == "POST" and item[1] == "sessions")
    assert create[2]["requirePlanApproval"] is True
    assert "automationMode" not in create[2]
    assert "implementation plan itself" in create[2]["prompt"]
    assert "exact repository-relative file path" in create[2]["prompt"]
    assert not any(path.endswith(":approvePlan") for _, path, _, _ in client.requests)
    assert not any(path.endswith(":sendMessage") for _, path, _, _ in client.requests)
    assert provider.last_observed_state == "AWAITING_PLAN_APPROVAL"
    assert provider.last_proposal_mode == "derived-plan-steps"

    print(json.dumps({
        "ok": True,
        "require_plan_approval": True,
        "auto_create_pr_disabled": True,
        "approve_plan_never_called": True,
        "plan_step_fallback": True,
        "unapproved_terminal_state": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
