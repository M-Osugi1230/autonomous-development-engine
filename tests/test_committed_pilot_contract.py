from __future__ import annotations

from pathlib import Path

from ade import PilotAction, PilotContractStore


CONTRACT_PATH = Path(".autodev/pilot/contract.json")


def test_committed_phase11_pilot_contract_is_frozen_and_safe() -> None:
    contract = PilotContractStore(CONTRACT_PATH).load()

    assert contract.pilot_id == "one-minute-cli-command-guard-001"
    assert contract.target.repository == "M-Osugi1230/one-minute-thought-experiments"
    assert contract.target.base_branch == "main"
    assert contract.target.baseline_sha == "46d2d473305ca8c904f90c78bc8f8aabf3fd7319"

    assert contract.safety.require_human_activation is True
    assert contract.safety.max_tasks == 1
    assert contract.safety.max_consecutive_failures == 1
    assert PilotAction.MODIFY_FILES in contract.safety.allowed_actions
    assert PilotAction.OPEN_PULL_REQUEST in contract.safety.allowed_actions
    assert contract.safety.action_allowed(PilotAction.COMMENT) is False

    assert contract.safety.path_allowed("src/thought_pipeline/cli.py") is True
    assert contract.safety.path_allowed("tests/test_cli.py") is True
    assert contract.safety.path_allowed("src/thought_pipeline/core.py") is False
    assert contract.safety.path_allowed(".github/workflows/ci.yml") is False
    assert contract.safety.path_allowed("content/experiments.yaml") is False
    assert contract.safety.path_allowed("pyproject.toml") is False

    assert contract.provider_policy.allow_fallback_before_session is True
    assert contract.provider_policy.sticky_after_session is True
    assert contract.provider_policy.preferred_provider_ids == (
        "jules",
        "github-copilot",
    )

    checks = {check.check_id: check for check in contract.acceptance_checks}
    assert tuple(check.check_id for check in contract.acceptance_checks) == (
        "compile",
        "validate",
        "tests",
        "offline-generate",
    )
    assert checks["compile"].timeout_seconds == 120
    assert checks["validate"].timeout_seconds == 180
    assert checks["tests"].timeout_seconds == 300
    assert checks["offline-generate"].timeout_seconds == 300
