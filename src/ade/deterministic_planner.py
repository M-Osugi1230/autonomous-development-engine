from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from .planning_activation import PlanningGoalRequest


_JICHI_CANDIDATE = re.compile(
    r"data/candidates/([a-z0-9-]+-city)/review_candidate\.json"
)
_CHU_BATCH = re.compile(r"ade-batch-(\d{3})")


class DeterministicPlanningProvider:
    """Trusted local PlanningProvider for bounded, recipe-backed plans."""

    provider_name = "deterministic"
    last_plan_steps: tuple[dict[str, str], ...] = ()
    last_observed_state = "LOCAL_DETERMINISTIC"
    last_proposal_mode = "deterministic-recipe"
    last_execution_boundary_crossed = False

    def __init__(self, proposal: dict[str, Any]) -> None:
        if not isinstance(proposal, dict):
            raise ValueError("proposal must be a JSON object")
        self._proposal = deepcopy(proposal)

    def propose(self, prompt: str) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("planner prompt must be non-empty")
        return deepcopy(self._proposal)


def _within(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        path == prefix.rstrip("/")
        or path.startswith(prefix.rstrip("/") + "/")
        for prefix in prefixes
    )


def _jichi_recipe(
    request: PlanningGoalRequest,
    *,
    existing_paths: frozenset[str],
) -> dict[str, Any] | None:
    if request.target_repository != "M-Osugi1230/jichi-insight":
        return None
    match = _JICHI_CANDIDATE.search(request.goal)
    if match is None:
        return None
    if not (request.min_tasks <= 1 <= request.max_tasks):
        return None

    city_slug = match.group(1)
    city_key = city_slug.removesuffix("-city").replace("-", "_")
    candidate_path = f"data/candidates/{city_slug}/review_candidate.json"
    test_path = f"tests/test_phase15_{city_key}_review_candidate_staging.py"

    allowed: list[str] = []
    for path in (candidate_path, test_path):
        if _within(path, request.allowed_path_prefixes):
            allowed.append(path)
    if candidate_path not in allowed:
        return None

    new_paths = [path for path in allowed if path not in existing_paths]
    return {
        "schema_version": 1,
        "goal": request.goal,
        "tasks": [
            {
                "key": "deterministic-step-001",
                "title": f"Stage {city_slug} Phase 15 review candidate",
                "outcome": (
                    "Create or complete the municipality's non-public Phase 15 "
                    "review candidate and deterministic candidate regression coverage "
                    "while preserving the repository's human-review boundary."
                ),
                "depends_on": [],
                "allowed_paths": allowed,
                "acceptance": [
                    "Candidate remains non-public with human review pending and publication ineligible.",
                    "Official-source evidence, period/version/fiscal boundaries, and deferred depth remain explicit.",
                    "Relevant repository validation and regression tests remain green.",
                ],
                "new_paths": new_paths,
                "human_only": False,
                "human_reason": None,
            }
        ],
        "human_boundaries": list(
            request.planner_policy().required_human_boundaries
        ),
    }


def _next_unused_batch_numbers(
    existing_paths: frozenset[str],
    *,
    start: int,
    count: int,
) -> tuple[int, ...]:
    numbers: list[int] = []
    candidate = start
    while len(numbers) < count:
        path = (
            "operations/plan-detection/candidates/"
            f"ade-batch-{candidate:03d}/candidates-v1.json"
        )
        if path not in existing_paths:
            numbers.append(candidate)
        candidate += 1
    return tuple(numbers)


def _chu_kei_recipe(
    request: PlanningGoalRequest,
    *,
    existing_paths: frozenset[str],
) -> dict[str, Any] | None:
    if request.target_repository != "M-Osugi1230/chu-kei":
        return None
    if "Plan Detection" not in request.goal:
        return None
    match = _CHU_BATCH.search(request.goal)
    if match is None:
        return None
    task_count = request.min_tasks
    if task_count < 1 or task_count > request.max_tasks:
        return None

    root = "operations/plan-detection/candidates"
    if not _within(root + "/placeholder.json", request.allowed_path_prefixes):
        return None

    start = int(match.group(1))
    numbers = _next_unused_batch_numbers(
        existing_paths,
        start=start,
        count=task_count,
    )
    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for index, batch_number in enumerate(numbers, 1):
        key = f"deterministic-step-{index:03d}"
        batch_id = f"ade-batch-{batch_number:03d}"
        path = f"{root}/{batch_id}/candidates-v1.json"
        tasks.append(
            {
                "key": key,
                "title": f"Stage Plan Detection candidate batch {batch_id}",
                "outcome": (
                    "Create one bounded non-public Plan Detection candidate batch "
                    "from official or first-party primary sources, selecting distinct "
                    "high-priority not_checked companies and preserving all review, "
                    "publication, and promotion boundaries."
                ),
                "depends_on": [previous] if previous is not None else [],
                "allowed_paths": [path],
                "acceptance": [
                    "The new batch passes the existing Plan Detection candidate validator.",
                    "npm run quality:v43 remains green.",
                    "Published Plan Detection state remains unchanged and every candidate remains pending human review.",
                ],
                "new_paths": [path],
                "human_only": False,
                "human_reason": None,
            }
        )
        previous = key

    return {
        "schema_version": 1,
        "goal": request.goal,
        "tasks": tasks,
        "human_boundaries": list(
            request.planner_policy().required_human_boundaries
        ),
    }


def _jquants_recipe(
    request: PlanningGoalRequest,
    *,
    existing_paths: frozenset[str],
) -> dict[str, Any] | None:
    if request.target_repository != "M-Osugi1230/jquants-research-studio":
        return None
    goal = request.goal.casefold()
    required_markers = (
        "quarterly earnings",
        "forward returns",
        "shareholder benefits",
    )
    if not all(marker in goal for marker in required_markers):
        return None
    if not (request.min_tasks <= 3 <= request.max_tasks):
        return None

    groups = (
        (
            "Deepen earnings and forecast point-in-time history",
            (
                "engine/features/fundamental_pit.py",
                "engine/marketdata/quarterly.py",
                "tests/test_fundamental_pit.py",
            ),
            (
                "Extend earnings history and retain forecast revisions as point-in-time snapshots.",
                "Preserve multi-year quarterly disclosures, provenance, and stale/missing-state semantics.",
                "Fundamental point-in-time regression coverage remains green.",
            ),
        ),
        (
            "Build forward-return and benchmark-relative event outcomes",
            (
                "engine/features/security_daily.py",
                "engine/marketdata/prices.py",
                "tests/test_security_features.py",
            ),
            (
                "Compute 1/5/20/60-trading-day forward-return and event features from stored price data.",
                "Preserve benchmark-relative return semantics without unbounded provider fetching.",
                "Security feature regression coverage remains green.",
            ),
        ),
        (
            "Normalize shareholder-benefit and total-yield inputs",
            (
                "engine/marketdata/benefit_parser.py",
                "engine/marketdata/dividend_yield.py",
            ),
            (
                "Normalize annual benefit value and investable-capital thresholds only to decision-useful depth.",
                "Calculate combined dividend and benefit yield while preserving missing/stale states.",
                "Repository CI remains green.",
            ),
        ),
    )

    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for index, (title, paths, acceptance) in enumerate(groups, 1):
        if not all(_within(path, request.allowed_path_prefixes) for path in paths):
            return None
        key = f"deterministic-step-{index:03d}"
        tasks.append(
            {
                "key": key,
                "title": title,
                "outcome": (
                    "Implement the bounded J-Quants data-depth slice across its "
                    "closely related implementation and regression files while "
                    "preserving quota, resumability, provenance, and point-in-time semantics."
                ),
                "depends_on": [previous] if previous is not None else [],
                "allowed_paths": list(paths),
                "acceptance": list(acceptance),
                "new_paths": [
                    path for path in paths if path not in existing_paths
                ],
                "human_only": False,
                "human_reason": None,
            }
        )
        previous = key

    return {
        "schema_version": 1,
        "goal": request.goal,
        "tasks": tasks,
        "human_boundaries": list(
            request.planner_policy().required_human_boundaries
        ),
    }


def build_deterministic_proposal(
    request: PlanningGoalRequest,
    *,
    existing_paths: frozenset[str] | set[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    if not isinstance(request, PlanningGoalRequest):
        raise ValueError("request must be a PlanningGoalRequest")
    normalized = frozenset(existing_paths)
    for recipe in (_jichi_recipe, _chu_kei_recipe, _jquants_recipe):
        proposal = recipe(request, existing_paths=normalized)
        if proposal is not None:
            return proposal
    return None
