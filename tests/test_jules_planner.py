from __future__ import annotations

import json
import unittest

from ade.jules_planner import (
    JulesPlannerConfig,
    JulesPlannerError,
    JulesPlanningProvider,
    extract_structured_proposal,
    latest_plan_steps,
)


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


class FakeClient:
    def __init__(self, *, initial_activities=None, post_message_activities=None, states=None):
        self.initial_activities = initial_activities or []
        self.post_message_activities = post_message_activities or self.initial_activities
        self.states = iter(states or ["AWAITING_PLAN_APPROVAL"] * 20)
        self.sent = []
        self.created = []
        self.activity_calls = 0

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "session-1", "state": "QUEUED"}

    def get_session(self, session_id):
        return {"id": session_id, "state": next(self.states)}

    def list_activities(self, session_id, *, page_size=100):
        self.activity_calls += 1
        if self.sent:
            return self.post_message_activities
        return self.initial_activities

    def send_message(self, session_id, prompt):
        self.sent.append((session_id, prompt))


class FlakyActivitiesClient(FakeClient):
    def list_activities(self, session_id, *, page_size=100):
        self.activity_calls += 1
        if self.activity_calls < 3:
            raise RuntimeError("HTTP 404: Requested entity was not found")
        return self.initial_activities


class JulesPlannerTests(unittest.TestCase):
    def test_extracts_json_from_agent_message(self):
        activities = [{"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}}]
        self.assertEqual(extract_structured_proposal(activities), PROPOSAL)

    def test_records_plan_generated_steps(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [
                        {"title": "Create helper", "description": "Allowed path: src/ade/helper.py"},
                        {"title": "Add tests", "description": "Allowed path: tests/test_helper.py"},
                    ]
                }
            }
        }]
        self.assertEqual(
            latest_plan_steps(activities),
            (
                {"title": "Create helper", "description": "Allowed path: src/ade/helper.py"},
                {"title": "Add tests", "description": "Allowed path: tests/test_helper.py"},
            ),
        )

    def test_plan_only_session_never_auto_executes_or_creates_pr(self):
        client = FakeClient(
            initial_activities=[{"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}}],
            states=["AWAITING_PLAN_APPROVAL", "AWAITING_PLAN_APPROVAL"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                max_structured_polls=3,
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose("Return a strict proposal")
        self.assertEqual(result, PROPOSAL)
        self.assertEqual(client.created[0]["require_plan_approval"], True)
        self.assertEqual(client.created[0]["auto_create_pr"], False)
        self.assertEqual(client.sent, [])

    def test_followup_requests_json_without_approving_plan(self):
        initial = [{
            "planGenerated": {
                "plan": {
                    "steps": [{"title": "Implement helper", "description": "Add src/ade/helper.py"}]
                }
            }
        }]
        after = initial + [{"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}}]
        client = FakeClient(
            initial_activities=initial,
            post_message_activities=after,
            states=[
                "AWAITING_PLAN_APPROVAL",
                "AWAITING_PLAN_APPROVAL",
                "AWAITING_PLAN_APPROVAL",
            ],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                max_structured_polls=3,
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose("Trusted planning request")
        self.assertEqual(result, PROPOSAL)
        self.assertEqual(len(client.sent), 1)
        self.assertIn("Do NOT approve the plan", client.sent[0][1])
        self.assertEqual(provider.last_observed_state, "AWAITING_PLAN_APPROVAL")

    def test_activity_404_eventual_consistency_is_bounded(self):
        activities = [{"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}}]
        client = FlakyActivitiesClient(
            initial_activities=activities,
            states=["AWAITING_PLAN_APPROVAL", "AWAITING_PLAN_APPROVAL"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                max_structured_polls=3,
                activity_404_retries=3,
            ),
            sleeper=lambda _: None,
        )
        self.assertEqual(provider.propose("Return proposal"), PROPOSAL)
        self.assertEqual(client.activity_calls, 3)

    def test_execution_boundary_violation_is_rejected(self):
        client = FakeClient(states=["IN_PROGRESS"])
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=1,
            ),
            sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(JulesPlannerError, "execution boundary"):
            provider.propose("Return proposal")


if __name__ == "__main__":
    unittest.main()
