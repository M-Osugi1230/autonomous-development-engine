from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .pilot import PilotContract
from .pilot_activation import pilot_contract_fingerprint


_SHA = re.compile(r"^[0-9a-f]{40,64}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def _normalize_timestamp(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("completed_at must be a timezone-aware ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "completed_at must be a timezone-aware ISO-8601 string"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("completed_at must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_github_url(url: str, *, repository: str, kind: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"{kind} URL must be a non-empty string")
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.netloc != "github.com":
        raise ValueError(f"{kind} URL must use https://github.com")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{kind} URL must not contain credentials, query, or fragment")
    prefix = f"/{repository}/"
    if not parsed.path.startswith(prefix):
        raise ValueError(f"{kind} URL must belong to {repository}")
    return value


@dataclass(frozen=True, slots=True)
class PilotAcceptanceEvidence:
    check_id: str
    command: str
    passed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.check_id, str) or not self.check_id.strip():
            raise ValueError("check_id must be a non-empty string")
        if not isinstance(self.command, str) or not self.command.strip():
            raise ValueError("command must be a non-empty string")
        if type(self.passed) is not bool:
            raise ValueError("passed must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "command": self.command,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotAcceptanceEvidence":
        if not isinstance(payload, dict):
            raise ValueError("acceptance evidence must be a JSON object")
        return cls(
            check_id=payload.get("check_id"),
            command=payload.get("command"),
            passed=payload.get("passed"),
        )


@dataclass(frozen=True, slots=True)
class PilotFinalEvidence:
    pilot_id: str
    contract_fingerprint: str
    target_repository: str
    baseline_sha: str
    base_branch: str
    pull_request_base_sha: str
    changed_paths: tuple[str, ...]
    final_head_sha: str
    pull_request_url: str
    ci_evidence_urls: tuple[str, ...]
    provider_id: str
    acceptance_checks: tuple[PilotAcceptanceEvidence, ...]
    rollback_boundary_sha: str
    completed_at: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("pilot final evidence schema_version must be 1")
        if not isinstance(self.pilot_id, str) or not self.pilot_id.strip():
            raise ValueError("pilot_id must be a non-empty string")
        if (
            not isinstance(self.contract_fingerprint, str)
            or not _FINGERPRINT.fullmatch(self.contract_fingerprint)
        ):
            raise ValueError("contract_fingerprint must be a lowercase SHA-256 digest")
        if not isinstance(self.target_repository, str) or "/" not in self.target_repository:
            raise ValueError("target_repository must be in OWNER/REPO form")
        if not isinstance(self.baseline_sha, str) or not _SHA.fullmatch(self.baseline_sha):
            raise ValueError("baseline_sha must be a lowercase Git SHA")
        if not isinstance(self.base_branch, str) or not self.base_branch.strip():
            raise ValueError("base_branch must be a non-empty string")
        if (
            not isinstance(self.pull_request_base_sha, str)
            or not _SHA.fullmatch(self.pull_request_base_sha)
        ):
            raise ValueError("pull_request_base_sha must be a lowercase Git SHA")
        if self.pull_request_base_sha != self.baseline_sha:
            raise ValueError("pull_request_base_sha must equal the frozen baseline SHA")

        raw_paths = self.changed_paths
        if not isinstance(raw_paths, tuple):
            try:
                raw_paths = tuple(raw_paths)
            except TypeError as exc:
                raise ValueError("changed_paths must be iterable") from exc
        if not raw_paths:
            raise ValueError("changed_paths must not be empty")
        normalized_paths: list[str] = []
        for path in raw_paths:
            if not isinstance(path, str) or not path.strip():
                raise ValueError("changed_paths must contain non-empty strings")
            normalized = path.strip()
            if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
                raise ValueError("changed_paths must be repository-relative paths")
            normalized_paths.append(normalized)
        if len(set(normalized_paths)) != len(normalized_paths):
            raise ValueError("changed_paths must not contain duplicates")
        object.__setattr__(self, "changed_paths", tuple(normalized_paths))

        if not isinstance(self.final_head_sha, str) or not _SHA.fullmatch(self.final_head_sha):
            raise ValueError("final_head_sha must be a lowercase Git SHA")
        if self.final_head_sha == self.baseline_sha:
            raise ValueError("final_head_sha must differ from baseline_sha")

        pr_url = _validate_github_url(
            self.pull_request_url,
            repository=self.target_repository,
            kind="pull request",
        )
        pr_tail = pr_url.removeprefix(
            f"https://github.com/{self.target_repository}/pull/"
        )
        if not pr_tail.isdigit():
            raise ValueError("pull request URL must identify a numeric PR")

        raw_ci = self.ci_evidence_urls
        if not isinstance(raw_ci, tuple):
            try:
                raw_ci = tuple(raw_ci)
            except TypeError as exc:
                raise ValueError("ci_evidence_urls must be iterable") from exc
        if not raw_ci:
            raise ValueError("ci_evidence_urls must not be empty")
        normalized_ci: list[str] = []
        for url in raw_ci:
            normalized = _validate_github_url(
                url,
                repository=self.target_repository,
                kind="CI evidence",
            )
            expected_prefix = (
                f"https://github.com/{self.target_repository}/actions/runs/"
            )
            tail = normalized.removeprefix(expected_prefix)
            if normalized == tail or not tail or not tail.split("/", 1)[0].isdigit():
                raise ValueError("CI evidence URL must identify a GitHub Actions run")
            normalized_ci.append(normalized)
        if len(set(normalized_ci)) != len(normalized_ci):
            raise ValueError("ci_evidence_urls must not contain duplicates")
        object.__setattr__(self, "ci_evidence_urls", tuple(normalized_ci))

        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")

        raw_checks = self.acceptance_checks
        if not isinstance(raw_checks, tuple):
            try:
                raw_checks = tuple(raw_checks)
            except TypeError as exc:
                raise ValueError("acceptance_checks must be iterable") from exc
        if not raw_checks:
            raise ValueError("acceptance_checks must not be empty")
        seen: set[str] = set()
        for check in raw_checks:
            if not isinstance(check, PilotAcceptanceEvidence):
                raise ValueError(
                    "acceptance_checks must contain PilotAcceptanceEvidence values"
                )
            if check.check_id in seen:
                raise ValueError(f"duplicate acceptance evidence: {check.check_id}")
            if not check.passed:
                raise ValueError("final pilot evidence requires every acceptance check to pass")
            seen.add(check.check_id)
        object.__setattr__(self, "acceptance_checks", raw_checks)

        if self.rollback_boundary_sha != self.baseline_sha:
            raise ValueError("rollback_boundary_sha must equal the frozen baseline SHA")
        object.__setattr__(self, "completed_at", _normalize_timestamp(self.completed_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pilot_id": self.pilot_id,
            "contract_fingerprint": self.contract_fingerprint,
            "target_repository": self.target_repository,
            "baseline_sha": self.baseline_sha,
            "base_branch": self.base_branch,
            "pull_request_base_sha": self.pull_request_base_sha,
            "changed_paths": list(self.changed_paths),
            "final_head_sha": self.final_head_sha,
            "pull_request_url": self.pull_request_url,
            "ci_evidence_urls": list(self.ci_evidence_urls),
            "provider_id": self.provider_id,
            "acceptance_checks": [
                check.to_dict() for check in self.acceptance_checks
            ],
            "rollback_boundary_sha": self.rollback_boundary_sha,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PilotFinalEvidence":
        if not isinstance(payload, dict):
            raise ValueError("pilot final evidence must be a JSON object")
        checks = payload.get("acceptance_checks")
        if not isinstance(checks, list):
            raise ValueError("acceptance_checks must be a list")
        ci_urls = payload.get("ci_evidence_urls")
        if not isinstance(ci_urls, list):
            raise ValueError("ci_evidence_urls must be a list")
        changed_paths = payload.get("changed_paths")
        if not isinstance(changed_paths, list):
            raise ValueError("changed_paths must be a list")
        return cls(
            schema_version=payload.get("schema_version"),
            pilot_id=payload.get("pilot_id"),
            contract_fingerprint=payload.get("contract_fingerprint"),
            target_repository=payload.get("target_repository"),
            baseline_sha=payload.get("baseline_sha"),
            base_branch=payload.get("base_branch"),
            pull_request_base_sha=payload.get("pull_request_base_sha"),
            changed_paths=tuple(changed_paths),
            final_head_sha=payload.get("final_head_sha"),
            pull_request_url=payload.get("pull_request_url"),
            ci_evidence_urls=tuple(ci_urls),
            provider_id=payload.get("provider_id"),
            acceptance_checks=tuple(
                PilotAcceptanceEvidence.from_dict(item) for item in checks
            ),
            rollback_boundary_sha=payload.get("rollback_boundary_sha"),
            completed_at=payload.get("completed_at"),
        )


def build_pilot_final_evidence(
    contract: PilotContract,
    *,
    base_branch: str,
    pull_request_base_sha: str,
    changed_paths: Iterable[str],
    final_head_sha: str,
    pull_request_url: str,
    ci_evidence_urls: Iterable[str],
    provider_id: str,
    acceptance_results: Mapping[str, bool],
    completed_at: str,
) -> PilotFinalEvidence:
    if not isinstance(contract, PilotContract):
        raise TypeError("contract must be a PilotContract")
    if provider_id not in contract.provider_policy.allowed_provider_ids:
        raise ValueError("provider_id is not allowed by the pilot contract")
    if base_branch != contract.target.base_branch:
        raise ValueError("pull request base branch does not match the pilot contract")
    normalized_base_sha = pull_request_base_sha.lower()
    if normalized_base_sha != contract.target.baseline_sha:
        raise ValueError("pull request base SHA does not match the frozen baseline")

    normalized_paths = tuple(changed_paths)
    if not normalized_paths:
        raise ValueError("changed_paths must not be empty")
    disallowed_paths = [
        path for path in normalized_paths if not contract.safety.path_allowed(path)
    ]
    if disallowed_paths:
        raise ValueError(
            f"pull request changed paths outside the pilot safety envelope: {disallowed_paths}"
        )

    expected_ids = {check.check_id for check in contract.acceptance_checks}
    if set(acceptance_results) != expected_ids:
        raise ValueError("acceptance_results must exactly match contract check IDs")

    checks = tuple(
        PilotAcceptanceEvidence(
            check_id=check.check_id,
            command=check.command,
            passed=acceptance_results[check.check_id],
        )
        for check in contract.acceptance_checks
    )
    return PilotFinalEvidence(
        pilot_id=contract.pilot_id,
        contract_fingerprint=pilot_contract_fingerprint(contract),
        target_repository=contract.target.repository,
        baseline_sha=contract.target.baseline_sha,
        base_branch=base_branch,
        pull_request_base_sha=normalized_base_sha,
        changed_paths=normalized_paths,
        final_head_sha=final_head_sha.lower(),
        pull_request_url=pull_request_url,
        ci_evidence_urls=tuple(ci_evidence_urls),
        provider_id=provider_id,
        acceptance_checks=checks,
        rollback_boundary_sha=contract.target.baseline_sha,
        completed_at=completed_at,
    )
