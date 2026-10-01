from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from .release_approval import ReleaseApprovalDecision
from .release_candidate import ReleaseEnvironment
from .release_policy import ReleaseTransitionPlan


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ReleaseDeploymentError(ValueError):
    """Trusted release-deployment boundary validation failed."""


class ReleaseDeploymentStatus(StrEnum):
    ARMED = "ARMED"
    DISPATCHED = "DISPATCHED"
    DEPLOYED = "DEPLOYED"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _safe_id(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ReleaseDeploymentError(f"{field} is invalid")
    return value


def _repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise ReleaseDeploymentError("repository must be owner/name")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ReleaseDeploymentError("repository must be owner/name")
    return value


def _sha40(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ReleaseDeploymentError(
            f"{field} must be a lowercase 40-char SHA"
        )
    return value


def _sha256(value: str, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReleaseDeploymentError(f"{field} must be sha256")
    return value


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentInvocation:
    deployment_request_id: str
    idempotency_key: str
    repository: str
    source_sha: str
    environment: ReleaseEnvironment
    transition_id: str
    transition_fingerprint: str
    approval_fingerprint: str
    adapter_implementation_id: str
    registry_fingerprint: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseDeploymentError(
                "unsupported deployment invocation schema version"
            )
        object.__setattr__(
            self,
            "deployment_request_id",
            _safe_id(
                self.deployment_request_id,
                field="deployment_request_id",
            ),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _safe_id(self.idempotency_key, field="idempotency_key"),
        )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "source_sha",
            _sha40(self.source_sha, field="source_sha"),
        )
        if not isinstance(self.environment, ReleaseEnvironment):
            raise ReleaseDeploymentError(
                "environment must be ReleaseEnvironment"
            )
        object.__setattr__(
            self,
            "transition_id",
            _safe_id(self.transition_id, field="transition_id"),
        )
        object.__setattr__(
            self,
            "transition_fingerprint",
            _sha256(
                self.transition_fingerprint,
                field="transition_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "approval_fingerprint",
            _sha256(
                self.approval_fingerprint,
                field="approval_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "adapter_implementation_id",
            _safe_id(
                self.adapter_implementation_id,
                field="adapter_implementation_id",
            ),
        )
        object.__setattr__(
            self,
            "registry_fingerprint",
            _sha256(
                self.registry_fingerprint,
                field="registry_fingerprint",
            ),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "deployment_request_id": self.deployment_request_id,
            "idempotency_key": self.idempotency_key,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "environment": self.environment.value,
            "transition_id": self.transition_id,
            "transition_fingerprint": self.transition_fingerprint,
            "approval_fingerprint": self.approval_fingerprint,
            "adapter_implementation_id": self.adapter_implementation_id,
            "registry_fingerprint": self.registry_fingerprint,
            "provider_defined": False,
            "contains_credentials": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentObservation:
    deployment_id: str
    repository: str
    source_sha: str
    environment: ReleaseEnvironment
    idempotency_key: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseDeploymentError(
                "unsupported deployment observation schema version"
            )
        object.__setattr__(
            self,
            "deployment_id",
            _safe_id(self.deployment_id, field="deployment_id"),
        )
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "source_sha",
            _sha40(self.source_sha, field="source_sha"),
        )
        if not isinstance(self.environment, ReleaseEnvironment):
            raise ReleaseDeploymentError(
                "environment must be ReleaseEnvironment"
            )
        object.__setattr__(
            self,
            "idempotency_key",
            _safe_id(self.idempotency_key, field="idempotency_key"),
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "deployment_id": self.deployment_id,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "environment": self.environment.value,
            "idempotency_key": self.idempotency_key,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


ReleaseDeployer = Callable[
    [ReleaseDeploymentInvocation],
    ReleaseDeploymentObservation,
]


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentAdapterRegistration:
    repository: str
    environment: ReleaseEnvironment
    implementation_id: str
    deployer: ReleaseDeployer

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", _repository(self.repository))
        if not isinstance(self.environment, ReleaseEnvironment):
            raise ReleaseDeploymentError(
                "environment must be ReleaseEnvironment"
            )
        object.__setattr__(
            self,
            "implementation_id",
            _safe_id(self.implementation_id, field="implementation_id"),
        )
        if not callable(self.deployer):
            raise ReleaseDeploymentError("deployer must be callable")

    @property
    def key(self) -> tuple[str, ReleaseEnvironment]:
        return (self.repository, self.environment)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "environment": self.environment.value,
            "implementation_id": self.implementation_id,
            "controller_owned": True,
            "idempotency_required": True,
        }


class TrustedReleaseDeploymentRegistry:
    def __init__(
        self,
        registrations: Iterable[ReleaseDeploymentAdapterRegistration],
    ) -> None:
        items = tuple(registrations)
        if not items:
            raise ReleaseDeploymentError(
                "trusted deployment registry must not be empty"
            )
        by_key: dict[
            tuple[str, ReleaseEnvironment],
            ReleaseDeploymentAdapterRegistration,
        ] = {}
        for registration in items:
            if not isinstance(
                registration,
                ReleaseDeploymentAdapterRegistration,
            ):
                raise ReleaseDeploymentError(
                    "deployment registry contains invalid registration"
                )
            if registration.key in by_key:
                raise ReleaseDeploymentError(
                    "duplicate deployment adapter registration"
                )
            by_key[registration.key] = registration
        self._registrations: Mapping[
            tuple[str, ReleaseEnvironment],
            ReleaseDeploymentAdapterRegistration,
        ] = MappingProxyType(dict(by_key))

    def resolve(
        self,
        repository: str,
        environment: ReleaseEnvironment,
    ) -> ReleaseDeploymentAdapterRegistration:
        repository = _repository(repository)
        if not isinstance(environment, ReleaseEnvironment):
            raise ReleaseDeploymentError(
                "environment must be ReleaseEnvironment"
            )
        registration = self._registrations.get((repository, environment))
        if registration is None:
            raise ReleaseDeploymentError(
                "no trusted deployment adapter for repository/environment"
            )
        return registration

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "registrations": [
                registration.canonical_dict()
                for _, registration in sorted(
                    self._registrations.items(),
                    key=lambda item: (
                        item[0][0],
                        item[0][1].value,
                    ),
                )
            ],
            "provider_defined": False,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentReceipt:
    deployment_request_id: str
    idempotency_key: str
    repository: str
    source_sha: str
    environment: ReleaseEnvironment
    transition_id: str
    transition_fingerprint: str
    approval_fingerprint: str
    adapter_implementation_id: str
    registry_fingerprint: str
    status: ReleaseDeploymentStatus
    dispatch_count: int
    deployment_id: str | None = None
    observation_fingerprint: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ReleaseDeploymentError(
                "unsupported deployment receipt schema version"
            )
        # Reuse invocation validation for all immutable identity fields.
        ReleaseDeploymentInvocation(
            deployment_request_id=self.deployment_request_id,
            idempotency_key=self.idempotency_key,
            repository=self.repository,
            source_sha=self.source_sha,
            environment=self.environment,
            transition_id=self.transition_id,
            transition_fingerprint=self.transition_fingerprint,
            approval_fingerprint=self.approval_fingerprint,
            adapter_implementation_id=self.adapter_implementation_id,
            registry_fingerprint=self.registry_fingerprint,
        )
        if not isinstance(self.status, ReleaseDeploymentStatus):
            object.__setattr__(
                self,
                "status",
                ReleaseDeploymentStatus(self.status),
            )
        if type(self.dispatch_count) is not int or self.dispatch_count < 0:
            raise ReleaseDeploymentError(
                "dispatch_count must be a non-negative integer"
            )

        if self.status is ReleaseDeploymentStatus.ARMED:
            if self.dispatch_count != 0:
                raise ReleaseDeploymentError(
                    "ARMED deployment must have dispatch_count 0"
                )
            if self.deployment_id is not None:
                raise ReleaseDeploymentError(
                    "ARMED deployment cannot have deployment_id"
                )
            if self.observation_fingerprint is not None:
                raise ReleaseDeploymentError(
                    "ARMED deployment cannot have observation fingerprint"
                )
        elif self.status is ReleaseDeploymentStatus.DISPATCHED:
            if self.dispatch_count != 1:
                raise ReleaseDeploymentError(
                    "DISPATCHED deployment must have dispatch_count 1"
                )
            if self.deployment_id is not None:
                raise ReleaseDeploymentError(
                    "DISPATCHED deployment cannot have deployment_id"
                )
            if self.observation_fingerprint is not None:
                raise ReleaseDeploymentError(
                    "DISPATCHED deployment cannot have observation fingerprint"
                )
        elif self.status is ReleaseDeploymentStatus.DEPLOYED:
            if self.dispatch_count != 1:
                raise ReleaseDeploymentError(
                    "DEPLOYED deployment must have dispatch_count 1"
                )
            if self.deployment_id is None:
                raise ReleaseDeploymentError(
                    "DEPLOYED deployment requires deployment_id"
                )
            _safe_id(self.deployment_id, field="deployment_id")
            if self.observation_fingerprint is None:
                raise ReleaseDeploymentError(
                    "DEPLOYED deployment requires observation fingerprint"
                )
            _sha256(
                self.observation_fingerprint,
                field="observation_fingerprint",
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "deployment_request_id": self.deployment_request_id,
            "idempotency_key": self.idempotency_key,
            "repository": self.repository,
            "source_sha": self.source_sha,
            "environment": self.environment.value,
            "transition_id": self.transition_id,
            "transition_fingerprint": self.transition_fingerprint,
            "approval_fingerprint": self.approval_fingerprint,
            "adapter_implementation_id": self.adapter_implementation_id,
            "registry_fingerprint": self.registry_fingerprint,
            "status": self.status.value,
            "dispatch_count": self.dispatch_count,
            "deployment_id": self.deployment_id,
            "observation_fingerprint": self.observation_fingerprint,
        }

    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_dict())


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentActivation:
    invocation: ReleaseDeploymentInvocation
    receipt: ReleaseDeploymentReceipt
    should_dispatch: bool


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentDispatch:
    receipt: ReleaseDeploymentReceipt
    changed: bool


@dataclass(frozen=True, slots=True)
class ReleaseDeploymentCompletion:
    receipt: ReleaseDeploymentReceipt
    observation: ReleaseDeploymentObservation
    changed: bool


def _receipt_identity_matches(
    receipt: ReleaseDeploymentReceipt,
    invocation: ReleaseDeploymentInvocation,
) -> bool:
    return (
        receipt.deployment_request_id == invocation.deployment_request_id
        and receipt.idempotency_key == invocation.idempotency_key
        and receipt.repository == invocation.repository
        and receipt.source_sha == invocation.source_sha
        and receipt.environment is invocation.environment
        and receipt.transition_id == invocation.transition_id
        and receipt.transition_fingerprint
        == invocation.transition_fingerprint
        and receipt.approval_fingerprint
        == invocation.approval_fingerprint
        and receipt.adapter_implementation_id
        == invocation.adapter_implementation_id
        and receipt.registry_fingerprint
        == invocation.registry_fingerprint
    )


def arm_release_deployment(
    *,
    transition: ReleaseTransitionPlan,
    approval: ReleaseApprovalDecision,
    registry: TrustedReleaseDeploymentRegistry,
    existing_receipt: ReleaseDeploymentReceipt | None = None,
) -> ReleaseDeploymentActivation:
    if not isinstance(transition, ReleaseTransitionPlan):
        raise ReleaseDeploymentError(
            "transition must be ReleaseTransitionPlan"
        )
    if not isinstance(approval, ReleaseApprovalDecision):
        raise ReleaseDeploymentError(
            "approval must be ReleaseApprovalDecision"
        )
    if not approval.approval_satisfied:
        raise ReleaseDeploymentError(
            "deployment requires explicit satisfied release approval"
        )
    if approval.transition_id != transition.transition_id:
        raise ReleaseDeploymentError(
            "approval transition id drift"
        )
    if approval.transition_fingerprint != transition.fingerprint():
        raise ReleaseDeploymentError(
            "approval transition fingerprint drift"
        )
    if not isinstance(registry, TrustedReleaseDeploymentRegistry):
        raise ReleaseDeploymentError(
            "registry must be TrustedReleaseDeploymentRegistry"
        )

    registration = registry.resolve(
        transition.repository,
        transition.to_environment,
    )
    approval_fingerprint = approval.fingerprint()
    seed = {
        "transition_id": transition.transition_id,
        "transition_fingerprint": transition.fingerprint(),
        "approval_fingerprint": approval_fingerprint,
        "repository": transition.repository,
        "source_sha": transition.source_sha,
        "environment": transition.to_environment.value,
        "adapter_implementation_id": registration.implementation_id,
        "registry_fingerprint": registry.fingerprint(),
    }
    digest = _fingerprint(seed)
    invocation = ReleaseDeploymentInvocation(
        deployment_request_id="deployment-" + digest[:24],
        idempotency_key="ade-release-" + digest[:32],
        repository=transition.repository,
        source_sha=transition.source_sha,
        environment=transition.to_environment,
        transition_id=transition.transition_id,
        transition_fingerprint=transition.fingerprint(),
        approval_fingerprint=approval_fingerprint,
        adapter_implementation_id=registration.implementation_id,
        registry_fingerprint=registry.fingerprint(),
    )
    expected = ReleaseDeploymentReceipt(
        deployment_request_id=invocation.deployment_request_id,
        idempotency_key=invocation.idempotency_key,
        repository=invocation.repository,
        source_sha=invocation.source_sha,
        environment=invocation.environment,
        transition_id=invocation.transition_id,
        transition_fingerprint=invocation.transition_fingerprint,
        approval_fingerprint=invocation.approval_fingerprint,
        adapter_implementation_id=invocation.adapter_implementation_id,
        registry_fingerprint=invocation.registry_fingerprint,
        status=ReleaseDeploymentStatus.ARMED,
        dispatch_count=0,
    )

    if existing_receipt is None:
        return ReleaseDeploymentActivation(
            invocation=invocation,
            receipt=expected,
            should_dispatch=True,
        )
    if not isinstance(existing_receipt, ReleaseDeploymentReceipt):
        raise ReleaseDeploymentError(
            "existing_receipt must be ReleaseDeploymentReceipt or null"
        )
    if not _receipt_identity_matches(existing_receipt, invocation):
        raise ReleaseDeploymentError(
            "existing deployment receipt identity drift"
        )
    return ReleaseDeploymentActivation(
        invocation=invocation,
        receipt=existing_receipt,
        should_dispatch=(
            existing_receipt.status is ReleaseDeploymentStatus.ARMED
        ),
    )


def record_release_deployment_dispatch(
    *,
    invocation: ReleaseDeploymentInvocation,
    receipt: ReleaseDeploymentReceipt,
) -> ReleaseDeploymentDispatch:
    if not isinstance(invocation, ReleaseDeploymentInvocation):
        raise ReleaseDeploymentError(
            "invocation must be ReleaseDeploymentInvocation"
        )
    if not isinstance(receipt, ReleaseDeploymentReceipt):
        raise ReleaseDeploymentError(
            "receipt must be ReleaseDeploymentReceipt"
        )
    if not _receipt_identity_matches(receipt, invocation):
        raise ReleaseDeploymentError(
            "deployment dispatch receipt identity drift"
        )
    if receipt.status is not ReleaseDeploymentStatus.ARMED:
        return ReleaseDeploymentDispatch(receipt=receipt, changed=False)

    dispatched = ReleaseDeploymentReceipt(
        deployment_request_id=receipt.deployment_request_id,
        idempotency_key=receipt.idempotency_key,
        repository=receipt.repository,
        source_sha=receipt.source_sha,
        environment=receipt.environment,
        transition_id=receipt.transition_id,
        transition_fingerprint=receipt.transition_fingerprint,
        approval_fingerprint=receipt.approval_fingerprint,
        adapter_implementation_id=receipt.adapter_implementation_id,
        registry_fingerprint=receipt.registry_fingerprint,
        status=ReleaseDeploymentStatus.DISPATCHED,
        dispatch_count=1,
    )
    return ReleaseDeploymentDispatch(
        receipt=dispatched,
        changed=True,
    )


def execute_trusted_release_deployment(
    *,
    registry: TrustedReleaseDeploymentRegistry,
    invocation: ReleaseDeploymentInvocation,
    dispatched_receipt: ReleaseDeploymentReceipt,
) -> ReleaseDeploymentObservation:
    if not isinstance(registry, TrustedReleaseDeploymentRegistry):
        raise ReleaseDeploymentError(
            "registry must be TrustedReleaseDeploymentRegistry"
        )
    if not isinstance(invocation, ReleaseDeploymentInvocation):
        raise ReleaseDeploymentError(
            "invocation must be ReleaseDeploymentInvocation"
        )
    if not isinstance(dispatched_receipt, ReleaseDeploymentReceipt):
        raise ReleaseDeploymentError(
            "dispatched_receipt must be ReleaseDeploymentReceipt"
        )
    if not _receipt_identity_matches(dispatched_receipt, invocation):
        raise ReleaseDeploymentError(
            "deployment execution receipt identity drift"
        )
    if (
        dispatched_receipt.status
        is not ReleaseDeploymentStatus.DISPATCHED
    ):
        raise ReleaseDeploymentError(
            "trusted deployment execution requires DISPATCHED receipt"
        )
    if dispatched_receipt.dispatch_count != 1:
        raise ReleaseDeploymentError(
            "trusted deployment execution requires single dispatch"
        )

    registration = registry.resolve(
        invocation.repository,
        invocation.environment,
    )
    if registration.implementation_id != invocation.adapter_implementation_id:
        raise ReleaseDeploymentError(
            "deployment adapter implementation drift"
        )
    if registry.fingerprint() != invocation.registry_fingerprint:
        raise ReleaseDeploymentError(
            "deployment registry fingerprint drift"
        )

    try:
        observation = registration.deployer(invocation)
    except Exception as exc:
        raise ReleaseDeploymentError(
            "trusted deployment adapter failed"
        ) from exc
    if not isinstance(observation, ReleaseDeploymentObservation):
        raise ReleaseDeploymentError(
            "trusted deployment adapter returned invalid observation"
        )
    if observation.repository != invocation.repository:
        raise ReleaseDeploymentError(
            "deployment observation repository drift"
        )
    if observation.source_sha != invocation.source_sha:
        raise ReleaseDeploymentError(
            "deployment observation source SHA drift"
        )
    if observation.environment is not invocation.environment:
        raise ReleaseDeploymentError(
            "deployment observation environment drift"
        )
    if observation.idempotency_key != invocation.idempotency_key:
        raise ReleaseDeploymentError(
            "deployment observation idempotency key drift"
        )
    return observation


def record_release_deployment_observation(
    *,
    invocation: ReleaseDeploymentInvocation,
    receipt: ReleaseDeploymentReceipt,
    observation: ReleaseDeploymentObservation,
) -> ReleaseDeploymentCompletion:
    if not isinstance(invocation, ReleaseDeploymentInvocation):
        raise ReleaseDeploymentError(
            "invocation must be ReleaseDeploymentInvocation"
        )
    if not isinstance(receipt, ReleaseDeploymentReceipt):
        raise ReleaseDeploymentError(
            "receipt must be ReleaseDeploymentReceipt"
        )
    if not isinstance(observation, ReleaseDeploymentObservation):
        raise ReleaseDeploymentError(
            "observation must be ReleaseDeploymentObservation"
        )
    if not _receipt_identity_matches(receipt, invocation):
        raise ReleaseDeploymentError(
            "deployment completion receipt identity drift"
        )
    if receipt.status is ReleaseDeploymentStatus.DEPLOYED:
        if (
            receipt.deployment_id != observation.deployment_id
            or receipt.observation_fingerprint
            != observation.fingerprint()
        ):
            raise ReleaseDeploymentError(
                "completed deployment observation drift"
            )
        return ReleaseDeploymentCompletion(
            receipt=receipt,
            observation=observation,
            changed=False,
        )
    if receipt.status is not ReleaseDeploymentStatus.DISPATCHED:
        raise ReleaseDeploymentError(
            "deployment observation requires DISPATCHED receipt"
        )
    if observation.repository != invocation.repository:
        raise ReleaseDeploymentError(
            "deployment observation repository drift"
        )
    if observation.source_sha != invocation.source_sha:
        raise ReleaseDeploymentError(
            "deployment observation source SHA drift"
        )
    if observation.environment is not invocation.environment:
        raise ReleaseDeploymentError(
            "deployment observation environment drift"
        )
    if observation.idempotency_key != invocation.idempotency_key:
        raise ReleaseDeploymentError(
            "deployment observation idempotency key drift"
        )

    completed = ReleaseDeploymentReceipt(
        deployment_request_id=receipt.deployment_request_id,
        idempotency_key=receipt.idempotency_key,
        repository=receipt.repository,
        source_sha=receipt.source_sha,
        environment=receipt.environment,
        transition_id=receipt.transition_id,
        transition_fingerprint=receipt.transition_fingerprint,
        approval_fingerprint=receipt.approval_fingerprint,
        adapter_implementation_id=receipt.adapter_implementation_id,
        registry_fingerprint=receipt.registry_fingerprint,
        status=ReleaseDeploymentStatus.DEPLOYED,
        dispatch_count=receipt.dispatch_count,
        deployment_id=observation.deployment_id,
        observation_fingerprint=observation.fingerprint(),
    )
    return ReleaseDeploymentCompletion(
        receipt=completed,
        observation=observation,
        changed=True,
    )
