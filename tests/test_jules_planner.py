from __future__ import annotations

import json
import unittest

from ade.jules_planner import (
    JulesPlannerConfig,
    JulesPlannerError,
    JulesPlanningProvider,
    derive_proposal_from_plan_steps,
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

    def test_derives_proposal_from_realistic_plan_steps(self):
        steps = (
            {
                "title": "Create string summary helper module in `src/ade/string_summary.py`.",
                "description": (
                    "Implement a pure helper that validates non-empty strings and returns "
                    "a deterministic dictionary. Allowed path: `src/ade/string_summary.py`"
                ),
            },
            {
                "title": "Create focused stdlib unit tests in `tests/test_string_summary.py`.",
                "description": (
                    "Cover valid inputs and invalid empty strings. "
                    "Allowed path: `tests/test_string_summary.py`"
                ),
            },
            {
                "title": "Complete pre commit steps.",
                "description": "Ensure testing and review are done.",
            },
        )
        proposal = derive_proposal_from_plan_steps(
            goal="Add helper",
            steps=steps,
            allowed_path_prefixes=("src/ade", "tests"),
        )
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(len(proposal["tasks"]), 2)
        self.assertEqual(
            proposal["tasks"][0]["allowed_paths"],
            ["src/ade/string_summary.py"],
        )
        self.assertEqual(
            proposal["tasks"][1]["allowed_paths"],
            ["tests/test_string_summary.py"],
        )
        self.assertEqual(
            proposal["tasks"][1]["depends_on"],
            ["jules-step-001"],
        )


    def test_plan_steps_are_derived_at_approval_boundary_without_followup(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [
                        {
                            "title": "Add helper in `src/ade/helper.py`",
                            "description": "Implement pure helper at `src/ade/helper.py`",
                        },
                        {
                            "title": "Add tests in `tests/test_helper.py`",
                            "description": "Add focused tests at `tests/test_helper.py`",
                        },
                    ]
                }
            }
        }]
        client = FakeClient(
            initial_activities=activities,
            states=["AWAITING_PLAN_APPROVAL"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                allowed_path_prefixes=("src/ade", "tests"),
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose(
            "You are an untrusted planning component. Goal: Add helper. "
            "Trusted writable roots: src/ade, tests. Maximum tasks: 8"
        )
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(client.sent, [])
        self.assertEqual(provider.last_observed_state, "AWAITING_PLAN_APPROVAL")
        self.assertEqual(provider.last_proposal_mode, "derived-plan-steps")

    def test_plan_snapshot_does_not_reenter_in_progress_to_request_json(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [
                        {
                            "title": "Add helper in `src/ade/helper.py`",
                            "description": "Implement helper at `src/ade/helper.py`",
                        }
                    ]
                }
            }
        }]
        client = FakeClient(
            initial_activities=activities,
            post_message_activities=activities + [
                {"agentMessaged": {"agentMessage": json.dumps(PROPOSAL)}}
            ],
            states=["AWAITING_PLAN_APPROVAL"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                allowed_path_prefixes=("src/ade",),
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose(
            "You are an untrusted planning component. Goal: Add helper. "
            "Trusted writable roots: src/ade. Maximum tasks: 8"
        )
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(client.sent, [])
        self.assertEqual(provider.last_proposal_mode, "derived-plan-steps")
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
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose("Return a strict proposal")
        self.assertEqual(result, PROPOSAL)
        self.assertEqual(client.created[0]["require_plan_approval"], True)
        self.assertEqual(client.created[0]["auto_create_pr"], False)
        self.assertEqual(client.sent, [])


    def test_approval_boundary_never_sends_followup_message(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [{
                        "title": "Implement helper in `src/ade/helper.py`",
                        "description": "Add deterministic helper at `src/ade/helper.py`",
                    }]
                }
            }
        }]
        client = FakeClient(
            initial_activities=activities,
            states=["AWAITING_PLAN_APPROVAL"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                allowed_path_prefixes=("src/ade",),
            ),
            sleeper=lambda _: None,
        )
        provider.propose(
            "You are an untrusted planning component. Goal: Add helper. "
            "Trusted writable roots: src/ade. Maximum tasks: 8"
        )
        self.assertEqual(client.sent, [])
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
                activity_404_retries=3,
            ),
            sleeper=lambda _: None,
        )
        self.assertEqual(provider.propose("Return proposal"), PROPOSAL)
        self.assertEqual(client.activity_calls, 3)


    def test_execution_boundary_plan_snapshot_is_rejected_even_with_plan_evidence(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [{
                        "title": "Add helper in `src/ade/helper.py`",
                        "description": "Implement helper at `src/ade/helper.py`",
                    }]
                }
            }
        }]
        client = FakeClient(
            initial_activities=activities,
            states=["COMPLETED"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=1,
                allowed_path_prefixes=("src/ade",),
            ),
            sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(JulesPlannerError, "crossed execution boundary"):
            provider.propose(
                "You are an untrusted planning component. Goal: Add helper. "
                "Trusted writable roots: src/ade. Maximum tasks: 8"
            )
        self.assertTrue(provider.last_execution_boundary_crossed)
        self.assertEqual(client.sent, [])
    def test_execution_boundary_without_plan_evidence_is_rejected(self):
        client = FakeClient(
            initial_activities=[],
            states=["COMPLETED"],
        )
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=1,
                allowed_path_prefixes=("src/ade",),
            ),
            sleeper=lambda _: None,
        )
        with self.assertRaisesRegex(JulesPlannerError, "crossed execution boundary"):
            provider.propose(
                "You are an untrusted planning component. Goal: Add helper. "
                "Trusted writable roots: src/ade. Maximum tasks: 8"
            )

    def test_in_progress_is_a_transient_planning_state_until_approval_boundary(self):
        activities = [{
            "planGenerated": {
                "plan": {
                    "steps": [{
                        "title": "Add helper in `src/ade/helper.py`",
                        "description": "Implement helper at `src/ade/helper.py`",
                    }]
                }
            }
        }]
        client = FakeClient(
            initial_activities=activities,
            states=[
                "IN_PROGRESS",
                "IN_PROGRESS",
                "AWAITING_PLAN_APPROVAL",
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
                max_plan_polls=4,
                allowed_path_prefixes=("src/ade",),
            ),
            sleeper=lambda _: None,
        )
        result = provider.propose(
            "You are an untrusted planning component. Goal: Add helper. "
            "Trusted writable roots: src/ade. Maximum tasks: 8"
        )
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(provider.last_observed_state, "AWAITING_PLAN_APPROVAL")
        self.assertFalse(provider.last_execution_boundary_crossed)
        self.assertEqual(provider.last_proposal_mode, "derived-plan-steps-fallback")

    def test_completed_execution_boundary_violation_is_rejected(self):
        client = FakeClient(states=["COMPLETED"])
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
