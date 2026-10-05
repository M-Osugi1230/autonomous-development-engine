from __future__ import annotations

import inspect
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus
from ade.runtime_verification_trigger import RuntimeVerificationPolicy
import runtime_probes as base_runtime_probes
from runtime_workspace import PreparedRuntimeWorkspace


CHU_KEI_REPOSITORY = "M-Osugi1230/chu-kei"
_CHU_CANDIDATE_PATH = re.compile(
    r"^operations/plan-detection/candidates/"
    r"(ade-batch-\d{3})/candidates-v1\.json$"
)
_PUBLISHED_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_STATUSES = frozenset(
    {"current", "expired", "found_unstructured", "not_checked"}
)
_ALLOWED_AUTHORITIES = frozenset(
    {"official_primary", "first_party_primary"}
)


def is_chu_kei_plan_detection_repository(repository: str) -> bool:
    return repository == CHU_KEI_REPOSITORY


def is_chu_kei_candidate_path(path: str) -> bool:
    return isinstance(path, str) and _CHU_CANDIDATE_PATH.fullmatch(path) is not None


def _safe_repository_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if value.startswith("/") or "\\" in value:
        return False
    parsed = PurePosixPath(value)
    return ".." not in parsed.parts and str(parsed) == value


def validate_chu_kei_candidate_payload(
    payload: object,
    *,
    expected_batch_id: str,
) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "chu-candidate-root-invalid"
    if payload.get("schemaVersion") != "plan-detection-candidate-batch-v1":
        return False, "chu-candidate-schema-invalid"
    if payload.get("batchId") != expected_batch_id:
        return False, "chu-candidate-batch-id-mismatch"
    if payload.get("nonPublic") is not True:
        return False, "chu-candidate-must-remain-non-public"

    policy = payload.get("policy")
    if not isinstance(policy, dict):
        return False, "chu-candidate-policy-missing"
    expected_policy = {
        "humanReviewRequired": True,
        "automaticPromotionAllowed": False,
        "publicationAllowed": False,
        "inferNoFormalPlanFromMissingEvidence": False,
        "finalRegistryMutationAllowed": False,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) is not expected:
            return False, f"chu-candidate-policy-{key}-invalid"

    allowed_statuses = policy.get("allowedSuggestedStatuses")
    if not isinstance(allowed_statuses, list):
        return False, "chu-candidate-allowed-statuses-missing"
    if set(allowed_statuses) != set(_ALLOWED_STATUSES):
        return False, "chu-candidate-allowed-statuses-drift"

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return False, "chu-candidate-list-empty"

    seen_codes: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False, "chu-candidate-entry-invalid"
        code = candidate.get("code")
        name = candidate.get("name")
        if not isinstance(code, str) or not code.strip():
            return False, "chu-candidate-code-missing"
        if code in seen_codes:
            return False, "chu-candidate-code-duplicate"
        seen_codes.add(code)
        if not isinstance(name, str) or not name.strip():
            return False, "chu-candidate-name-missing"

        source = candidate.get("source")
        if not isinstance(source, dict):
            return False, "chu-candidate-source-missing"
        if source.get("authority") not in _ALLOWED_AUTHORITIES:
            return False, "chu-candidate-source-authority-invalid"
        source_url = source.get("url")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            return False, "chu-candidate-source-url-invalid"
        published_date = source.get("publishedDate")
        if not isinstance(published_date, str) or _PUBLISHED_DATE.fullmatch(published_date) is None:
            return False, "chu-candidate-published-date-invalid"

        observation = candidate.get("observation")
        if not isinstance(observation, dict):
            return False, "chu-candidate-observation-missing"
        suggested = observation.get("suggestedStatus")
        if suggested not in _ALLOWED_STATUSES:
            return False, "chu-candidate-suggested-status-invalid"
        if suggested == "no_formal_plan":
            return False, "chu-candidate-no-formal-plan-forbidden"

        review = candidate.get("review")
        if not isinstance(review, dict):
            return False, "chu-candidate-review-missing"
        if review.get("decision") != "needs_review":
            return False, "chu-candidate-review-decision-invalid"
        if review.get("status") != "pending":
            return False, "chu-candidate-review-status-invalid"

        publication = candidate.get("publication")
        if not isinstance(publication, dict) or publication.get("eligible") is not False:
            return False, "chu-candidate-publication-must-remain-ineligible"
        promotion = candidate.get("promotion")
        if not isinstance(promotion, dict) or promotion.get("allowed") is not False:
            return False, "chu-candidate-promotion-must-remain-disabled"

        provenance = candidate.get("provenance")
        if not isinstance(provenance, dict):
            return False, "chu-candidate-provenance-missing"
        repository_paths = provenance.get("repositoryPaths")
        if not isinstance(repository_paths, list) or not repository_paths:
            return False, "chu-candidate-provenance-paths-missing"
        if any(not _safe_repository_path(path) for path in repository_paths):
            return False, "chu-candidate-provenance-path-invalid"

    return True, "chu-plan-detection-candidate-contract-pass"


def _chu_kei_candidate_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        root = workspace.root / "operations" / "plan-detection" / "candidates"
        candidates = sorted(root.glob("ade-batch-*/candidates-v1.json"))
        if len(candidates) != 1:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="chu-candidate-sparse-workspace-invalid",
            )
        candidate_path = candidates[0]
        match = _CHU_CANDIDATE_PATH.fullmatch(
            candidate_path.relative_to(workspace.root).as_posix()
        )
        if match is None:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="chu-candidate-path-invalid",
            )
        try:
            payload = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="chu-candidate-json-invalid",
            )
        valid, detail = validate_chu_kei_candidate_payload(
            payload,
            expected_batch_id=match.group(1),
        )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS if valid else RuntimeProbeStatus.FAIL,
            detail_code=detail,
        )

    return run


def _workspace_not_configured(
    _: RuntimeProbeInvocation,
) -> RuntimeProbeObservation:
    return RuntimeProbeObservation(
        RuntimeProbeStatus.ERROR,
        detail_code="runtime-workspace-not-configured",
    )


def _base_registry(
    workspace: PreparedRuntimeWorkspace | None,
    *,
    target_repository: str | None,
) -> TrustedRuntimeProbeRegistry:
    parameters = inspect.signature(
        base_runtime_probes.build_runtime_probe_registry
    ).parameters
    if "target_repository" in parameters:
        return base_runtime_probes.build_runtime_probe_registry(
            workspace,
            target_repository=target_repository,
        )
    return base_runtime_probes.build_runtime_probe_registry(workspace)


def build_runtime_probe_registry(
    workspace: PreparedRuntimeWorkspace | None = None,
    *,
    target_repository: str | None = None,
) -> TrustedRuntimeProbeRegistry:
    if is_chu_kei_plan_detection_repository(target_repository or ""):
        runner = (
            _chu_kei_candidate_runner(workspace)
            if workspace is not None
            else _workspace_not_configured
        )
        return TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    probe_id="chu-plan-detection-candidate-contract",
                    implementation_id="chu-plan-detection-candidate-contract-v1",
                    runner=runner,
                )
            ]
        )
    return _base_registry(
        workspace,
        target_repository=target_repository,
    )


def build_runtime_verification_policy(
    target_repository: str,
) -> RuntimeVerificationPolicy:
    if is_chu_kei_plan_detection_repository(target_repository):
        return RuntimeVerificationPolicy(
            target_repository=target_repository,
            environment="repository",
            required_probe_ids=(
                "chu-plan-detection-candidate-contract",
            ),
            max_attempts=2,
            timeout_seconds=120,
        )
    return base_runtime_probes.build_runtime_verification_policy(
        target_repository
    )
