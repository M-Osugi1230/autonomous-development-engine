from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ade import (
    PilotAcceptanceCheck,
    PilotAction,
    PilotContract,
    PilotEvidenceStore,
    PilotProviderPolicy,
    PilotSafetyEnvelope,
    PilotTarget,
    build_pilot_final_evidence,
)


def contract() -> PilotContract:
    return PilotContract(
        pilot_id="evidence-test",
        target=PilotTarget(
            repository="owner/repo",
            base_branch="main",
            baseline_sha="a" * 40,
        ),
        goal="Run one bounded production pilot.",
        safety=PilotSafetyEnvelope(
            allowed_path_prefixes=("src", "tests"),
            forbidden_path_prefixes=(".github", ".autodev"),
            allowed_actions=(
                PilotAction.READ,
                PilotAction.RUN_VALIDATION,
                PilotAction.OPEN_PULL_REQUEST,
            ),
        ),
        provider_policy=PilotProviderPolicy(
            allowed_provider_ids=("jules", "github-copilot"),
            preferred_provider_ids=("jules",),
        ),
        acceptance_checks=(
            PilotAcceptanceCheck(
                check_id="tests",
                command="python -m pytest -q",
                timeout_seconds=300,
            ),
            PilotAcceptanceCheck(
                check_id="compile",
                command="python -m compileall -q src",
                timeout_seconds=120,
            ),
        ),
    )


def build():
    return build_pilot_final_evidence(
        contract(),
        final_head_sha="b" * 40,
        pull_request_url="https://github.com/owner/repo/pull/17",
        ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
        provider_id="jules",
        acceptance_results={"tests": True, "compile": True},
        completed_at="2026-09-26T23:00:00+09:00",
    )


class PilotEvidenceTests(unittest.TestCase):
    def test_final_evidence_is_contract_bound_and_complete(self) -> None:
        evidence = build()

        self.assertEqual(evidence.target_repository, "owner/repo")
        self.assertEqual(evidence.baseline_sha, "a" * 40)
        self.assertEqual(evidence.final_head_sha, "b" * 40)
        self.assertEqual(evidence.rollback_boundary_sha, evidence.baseline_sha)
        self.assertEqual(evidence.provider_id, "jules")
        self.assertEqual(
            [check.check_id for check in evidence.acceptance_checks],
            ["tests", "compile"],
        )
        self.assertTrue(all(check.passed for check in evidence.acceptance_checks))
        self.assertEqual(evidence.completed_at, "2026-09-26T14:00:00Z")

    def test_final_evidence_rejects_failed_acceptance(self) -> None:
        with self.assertRaises(ValueError):
            build_pilot_final_evidence(
                contract(),
                final_head_sha="b" * 40,
                pull_request_url="https://github.com/owner/repo/pull/17",
                ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
                provider_id="jules",
                acceptance_results={"tests": False, "compile": True},
                completed_at="2026-09-26T14:00:00Z",
            )

    def test_final_evidence_rejects_unknown_provider_and_check_set(self) -> None:
        with self.assertRaises(ValueError):
            build_pilot_final_evidence(
                contract(),
                final_head_sha="b" * 40,
                pull_request_url="https://github.com/owner/repo/pull/17",
                ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
                provider_id="other",
                acceptance_results={"tests": True, "compile": True},
                completed_at="2026-09-26T14:00:00Z",
            )
        with self.assertRaises(ValueError):
            build_pilot_final_evidence(
                contract(),
                final_head_sha="b" * 40,
                pull_request_url="https://github.com/owner/repo/pull/17",
                ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
                provider_id="jules",
                acceptance_results={"tests": True},
                completed_at="2026-09-26T14:00:00Z",
            )

    def test_final_evidence_rejects_wrong_repository_urls_and_no_change(self) -> None:
        with self.assertRaises(ValueError):
            build_pilot_final_evidence(
                contract(),
                final_head_sha="a" * 40,
                pull_request_url="https://github.com/owner/repo/pull/17",
                ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
                provider_id="jules",
                acceptance_results={"tests": True, "compile": True},
                completed_at="2026-09-26T14:00:00Z",
            )
        with self.assertRaises(ValueError):
            build_pilot_final_evidence(
                contract(),
                final_head_sha="b" * 40,
                pull_request_url="https://github.com/other/repo/pull/17",
                ci_evidence_urls=("https://github.com/owner/repo/actions/runs/12345",),
                provider_id="jules",
                acceptance_results={"tests": True, "compile": True},
                completed_at="2026-09-26T14:00:00Z",
            )

    def test_final_evidence_store_round_trip(self) -> None:
        evidence = build()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final-evidence.json"
            store = PilotEvidenceStore(path)
            store.save(evidence)

            self.assertEqual(store.load(), evidence)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                evidence.to_dict(),
            )


if __name__ == "__main__":
    unittest.main()
