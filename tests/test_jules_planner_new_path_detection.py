from __future__ import annotations

import unittest

from ade.jules_planner import derive_proposal_from_plan_steps


class JulesPlannerNewPathDetectionTests(unittest.TestCase):
    def test_add_supabase_migration_is_declared_new_when_snapshot_is_truncated(self) -> None:
        path = "supabase/migrations/20261003000000_jq_market_outcomes_read_model.sql"
        proposal = derive_proposal_from_plan_steps(
            goal="Materialize production outcomes in Supabase",
            steps=(
                {
                    "title": f"Add Supabase migration `{path}`",
                    "description": "Create the production read-model migration and indexes.",
                },
            ),
            allowed_path_prefixes=("supabase",),
            known_existing_paths=frozenset(
                {"supabase/migrations/20260901000000_existing.sql"}
            ),
            repository_paths_complete=False,
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        task = proposal["tasks"][0]
        self.assertEqual(task["allowed_paths"], [path])
        self.assertEqual(task["new_paths"], [path])

    def test_creation_wording_never_marks_known_existing_path_as_new(self) -> None:
        path = "supabase/migrations/20260901000000_existing.sql"
        proposal = derive_proposal_from_plan_steps(
            goal="Update production materialization",
            steps=(
                {
                    "title": f"Add migration changes in `{path}`",
                    "description": "Adjust the existing migration contract.",
                },
            ),
            allowed_path_prefixes=("supabase",),
            known_existing_paths=frozenset({path}),
            repository_paths_complete=False,
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["tasks"][0]["new_paths"], [])

    def test_ambiguous_update_of_unknown_path_remains_not_declared_new(self) -> None:
        path = "supabase/migrations/possibly_existing.sql"
        proposal = derive_proposal_from_plan_steps(
            goal="Update production materialization",
            steps=(
                {
                    "title": f"Update `{path}`",
                    "description": "Adjust the materialization behavior.",
                },
            ),
            allowed_path_prefixes=("supabase",),
            known_existing_paths=frozenset(),
            repository_paths_complete=False,
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["tasks"][0]["new_paths"], [])

    def test_complete_snapshot_still_uses_repository_grounding_as_authority(self) -> None:
        path = "scripts/new_materialization.py"
        proposal = derive_proposal_from_plan_steps(
            goal="Add materialization helper",
            steps=(
                {
                    "title": f"Implement helper in `{path}`",
                    "description": "Build deterministic materialization support.",
                },
            ),
            allowed_path_prefixes=("scripts",),
            known_existing_paths=frozenset(),
            repository_paths_complete=True,
        )

        self.assertIsNotNone(proposal)
        assert proposal is not None
        self.assertEqual(proposal["tasks"][0]["new_paths"], [path])


if __name__ == "__main__":
    unittest.main()
