from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .release_candidate import ReleaseCandidate, ReleaseEnvironment


class ReleasePolicyError(ValueError):
    """Trusted release-promotion policy validation failed."""


_ORDERED_ENVIRONMENTS = (
    ReleaseEnvironment.PREVIEW,
    ReleaseEnvironment.STAGING,
    ReleaseEnvironment.PRODUCTION,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ReleasePromotionPolicy:
    ordered_environments: tuple[ReleaseEnvironment, ...] = _ORDERED_ENVIRONMENTS
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleasePolicyError(
                "unsupported release promotion policy schema version"
            )
        normalized = tuple(self.ordered_environments)
        if normalized != _ORDERED_ENVIRONMENTS:
            raise ReleasePolicyError(
                "release promotion order is controller-owned"
            )
        if any(
            not isinstance(item, ReleaseEnvironment)
            for item in normalized
        ):
            raise ReleasePolicyError(
                "ordered_environments must contain ReleaseEnvironment values"
            )
        object.__setattr__(self, "ordered_environments", normalized)

    @property
    def human_approval_required(self) -> bool:
        return True

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ordered_environments": [
                item.value for item in self.ordered_environments
            ],
            "human_approval_required": True,
            "provider_selects_environment": False,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReleasePromotionPolicy":
        if not isinstance(payload, dict):
            raise ReleasePolicyError(
                "release promotion policy must be a JSON object"
            )
        allowed = {
            "schema_version",
            "ordered_environments",
            "human_approval_required",
            "provider_selects_environment",
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ReleasePolicyError(
                f"unknown release promotion policy fields: {sorted(unknown)}"
            )
        if payload.get("human_approval_required") is not True:
            raise ReleasePolicyError(
                "release promotion policy must require human approval"
            )
        for field in (
            "provider_selects_environment",
            "deployment_authority",
            "promotion_authority",
            "auto_promote",
        ):
            if payload.get(field, False) is not False:
                raise ReleasePolicyError(
                    f"release promotion policy cannot grant {field.replace('_', ' ')}"
                )
        raw = payload.get("ordered_environments")
        if not isinstance(raw, list):
            raise ReleasePolicyError(
                "ordered_environments must be a list"
            )
        try:
            ordered = tuple(ReleaseEnvironment(item) for item in raw)
        except (TypeError, ValueError) as exc:
            raise ReleasePolicyError(
                "ordered_environments contains an invalid environment"
            ) from exc
        return cls(
            schema_version=payload.get("schema_version", 0),
            ordered_environments=ordered,
        )


@dataclass(frozen=True, slots=True)
class ReleaseTransitionPlan:
    transition_id: str
    release_candidate_id: str
    release_candidate_fingerprint: str
    repository: str
    source_sha: str
    from_environment: ReleaseEnvironment | None
    to_environment: ReleaseEnvironment
    policy_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleasePolicyError(
                "unsupported release transition schema version"
            )
        for field_name in (
            "transition_id",
            "release_candidate_id",
            "repository",
            "source_sha",
            "release_candidate_fingerprint",
            "policy_fingerprint",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ReleasePolicyError(
                    f"{field_name} must be non-empty"
                )
        for field_name in (
            "release_candidate_fingerprint",
            "policy_fingerprint",
        ):
            value = getattr(self, field_name)
            if (
                len(value) != 64
                or any(ch not in "0123456789abcdef" for ch in value)
            ):
                raise ReleasePolicyError(
                    f"{field_name} must be sha256"
                )
        if (
            len(self.source_sha) != 40
            or any(ch not in "0123456789abcdef" for ch in self.source_sha)
        ):
            raise ReleasePolicyError(
                "source_sha must be a lowercase 40-char SHA"
            )
        if self.from_environment is not None and not isinstance(
            self.from_environment,
            ReleaseEnvironment,
        ):
            raise ReleasePolicyError(
                "from_environment must be ReleaseEnvironment or null"
            )
        if not isinstance(self.to_environment, ReleaseEnvironment):
            raise ReleasePolicyError(
                "to_environment must be ReleaseEnvironment"
            )

    @property
    def requires_human_approval(self) -> bool:
        return True

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "transition_id": self.transition_id,
            "release_candidate_id": self.release_candidate_id,
            "release_candidate_fingerprint": (
                self.release_candidate_fingerprint
            ),
            "repository": self.repository,
            "source_sha": self.source_sha,
            "from_environment": (
                self.from_environment.value
                if self.from_environment is not None
                else None
            ),
            "to_environment": self.to_environment.value,
            "policy_fingerprint": self.policy_fingerprint,
            "requires_human_approval": True,
            "deployment_authority": False,
            "promotion_authority": False,
            "auto_promote": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


def _next_environment(
    policy: ReleasePromotionPolicy,
    current_verified_environment: ReleaseEnvironment | None,
) -> ReleaseEnvironment:
    if current_verified_environment is None:
        return policy.ordered_environments[0]
    if not isinstance(current_verified_environment, ReleaseEnvironment):
        raise ReleasePolicyError(
            "current_verified_environment must be ReleaseEnvironment or null"
        )
    try:
        index = policy.ordered_environments.index(current_verified_environment)
    except ValueError as exc:
        raise ReleasePolicyError(
            "current environment is outside trusted release policy"
        ) from exc
    if index == len(policy.ordered_environments) - 1:
        raise ReleasePolicyError(
            "production is terminal for release promotion"
        )
    return policy.ordered_environments[index + 1]


def plan_release_transition(
    *,
    candidate: ReleaseCandidate,
    current_verified_environment: ReleaseEnvironment | None,
    policy: ReleasePromotionPolicy | None = None,
) -> ReleaseTransitionPlan:
    if not isinstance(candidate, ReleaseCandidate):
        raise ReleasePolicyError(
            "candidate must be ReleaseCandidate"
        )
    policy = policy or ReleasePromotionPolicy()
    if not isinstance(policy, ReleasePromotionPolicy):
        raise ReleasePolicyError(
            "policy must be ReleasePromotionPolicy"
        )

    expected_target = _next_environment(
        policy,
        current_verified_environment,
    )
    if candidate.target_environment is not expected_target:
        raise ReleasePolicyError(
            "release candidate target does not match next trusted environment"
        )

    candidate_fingerprint = candidate.fingerprint()
    transition_payload = {
        "release_candidate_id": candidate.release_candidate_id,
        "release_candidate_fingerprint": candidate_fingerprint,
        "repository": candidate.repository,
        "source_sha": candidate.source_sha,
        "from_environment": (
            current_verified_environment.value
            if current_verified_environment is not None
            else None
        ),
        "to_environment": expected_target.value,
        "policy_fingerprint": policy.fingerprint(),
    }
    transition_id = "promotion-" + _fingerprint(transition_payload)[:24]
    return ReleaseTransitionPlan(
        transition_id=transition_id,
        release_candidate_id=candidate.release_candidate_id,
        release_candidate_fingerprint=candidate_fingerprint,
        repository=candidate.repository,
        source_sha=candidate.source_sha,
        from_environment=current_verified_environment,
        to_environment=expected_target,
        policy_fingerprint=policy.fingerprint(),
    )
