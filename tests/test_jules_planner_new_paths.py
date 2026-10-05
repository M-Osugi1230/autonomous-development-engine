from __future__ import annotations

import json
import unittest

from ade.jules_planner import (
    JulesPlannerConfig,
    JulesPlanningProvider,
    derive_proposal_from_plan_steps,
)


class _FakeClient:
    def __init__(self, activities):
        self.activities = activities
        self.created = []

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "session-1", "state": "QUEUED"}

    def get_session(self, session_id):
        return {"id": session_id, "state": "AWAITING_PLAN_APPROVAL"}

    def list_activities(self, session_id, *, page_size=100):
        return self.activities


class JulesPlannerNewPathsTests(unittest.TestCase):
    def test_complete_repository_grounding_marks_absent_path_new(self):
        steps = (
            {
                "title": "Update existing helper in `src/ade/existing.py`",
                "description": "Modify `src/ade/existing.py`",
            },
            {
                "title": "Create new helper in `src/ade/new_helper.py`",
                "description": "Create a new file at `src/ade/new_helper.py`",
            },
        )
        proposal = derive_proposal_from_plan_steps(
            goal="Add helper",
            steps=steps,
            allowed_path_prefixes=("src/ade",),
            known_existing_paths=frozenset({"src/ade/existing.py"}),
            repository_paths_complete=True,
        )
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["tasks"][0]["new_paths"], [])
        self.assertEqual(
            proposal["tasks"][1]["new_paths"],
            ["src/ade/new_helper.py"],
        )

    def test_truncated_repository_grounding_only_marks_explicit_creation(self):
        steps = (
            {
                "title": "Update helper in `src/ade/possibly_existing.py`",
                "description": "Modify `src/ade/possibly_existing.py`",
            },
            {
                "title": "Create a new migration `supabase/migrations/20261006000000_example.sql`",
                "description": "Create new migration file `supabase/migrations/20261006000000_example.sql`",
            },
        )
        proposal = derive_proposal_from_plan_steps(
            goal="Materialize production data",
            steps=steps,
            allowed_path_prefixes=("src/ade", "supabase"),
            known_existing_paths=frozenset(),
            repository_paths_complete=False,
        )
        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["tasks"][0]["new_paths"], [])
        self.assertEqual(
            proposal["tasks"][1]["new_paths"],
            ["supabase/migrations/20261006000000_example.sql"],
        )

    def test_provider_preserves_new_migration_intent_from_repository_context(self):
        activities = [
            {
                "planGenerated": {
                    "plan": {
                        "steps": [
                            {
                                "title": "Create a new migration `supabase/migrations/20261006000000_outcomes.sql`",
                                "description": "Create new migration file `supabase/migrations/20261006000000_outcomes.sql`",
                            },
                            {
                                "title": "Update cloud sync `supabase/functions/cloud-yield-sync/index.ts`",
                                "description": "Update `supabase/functions/cloud-yield-sync/index.ts`",
                            },
                        ]
                    }
                }
            }
        ]
        client = _FakeClient(activities)
        provider = JulesPlanningProvider(
            client,
            JulesPlannerConfig(
                source_name="sources/github/example/repo",
                poll_interval_seconds=0.001,
                max_plan_polls=3,
                allowed_path_prefixes=("supabase",),
            ),
            sleeper=lambda _: None,
        )
        repository_context = json.dumps(
            {
                "known_files_within_trusted_roots": [
                    "supabase/functions/cloud-yield-sync/index.ts"
                ],
                "known_files_truncated": True,
            },
            separators=(",", ":"),
        )
        prompt = (
            "You are an untrusted planning component. Goal: Materialize production data. "
            "Trusted writable roots: supabase. Maximum tasks: 8. "
            f"RepositoryStructureJSON={repository_context}."
        )
        result = provider.propose(prompt)
        self.assertEqual(
            result["tasks"][0]["new_paths"],
            ["supabase/migrations/20261006000000_outcomes.sql"],
        )
        self.assertEqual(result["tasks"][1]["new_paths"], [])
        self.assertEqual(provider.last_proposal_mode, "derived-plan-steps")


if __name__ == "__main__":
    unittest.main()
