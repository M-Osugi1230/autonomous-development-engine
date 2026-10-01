from __future__ import annotations

import json

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignal,
    ImprovementSignalError,
    ImprovementSignalKind,
    build_improvement_signal,
)


def main() -> int:
    try:
        signal = build_improvement_signal(
            repository=(
                "M-Osugi1230/one-minute-thought-experiments"
            ),
            source_sha=(
                "726431b60db8b25cdd4bc15bb1493a0060f36327"
            ),
            release_candidate_id=(
                "release-a4cd075b270b6ad434ae2602"
            ),
            release_environment="preview",
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement=(
                "Review the verified preview release for one bounded "
                "evidence-backed improvement opportunity."
            ),
            evidence_refs=(
                ImprovementEvidenceRef(
                    kind=(
                        ImprovementEvidenceKind.RELEASE_EVIDENCE
                    ),
                    path=(
                        ".autodev/campaign-evidence/"
                        "v1.8-autonomous-release-proof-001.json"
                    ),
                    fingerprint="a" * 64,
                ),
                ImprovementEvidenceRef(
                    kind=(
                        ImprovementEvidenceKind.POST_VERIFICATION
                    ),
                    path=(
                        ".autodev/release/proof/final/"
                        "post-verification-finalization.json"
                    ),
                    fingerprint="b" * 64,
                ),
            ),
            tags=("release", "verified"),
        )

        round_trip = ImprovementSignal.from_dict(
            signal.canonical_dict()
        )
        if round_trip != signal:
            raise AssertionError(
                "improvement signal round trip drift"
            )

        payload = signal.canonical_dict()
        forbidden_authority = (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
            "scope_expansion_authority",
            "acceptance_mutation_authority",
            "human_decision_authority",
        )
        for field in forbidden_authority:
            if payload[field] is not False:
                raise AssertionError(
                    f"improvement signal authority drift: {field}"
                )

        tampered = dict(payload)
        tampered["auto_dispatch"] = True
        try:
            ImprovementSignal.from_dict(tampered)
        except ImprovementSignalError:
            pass
        else:
            raise AssertionError(
                "serialized auto-dispatch authority must fail closed"
            )

        unknown = dict(payload)
        unknown["provider_priority"] = 1
        try:
            ImprovementSignal.from_dict(unknown)
        except ImprovementSignalError:
            pass
        else:
            raise AssertionError(
                "unknown signal fields must fail closed"
            )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-continuous-improvement-signal-foundation"
                    ),
                    "signal_id": signal.signal_id,
                    "fingerprint": signal.fingerprint(),
                    "repository": signal.repository,
                    "source_sha": signal.source_sha,
                    "release_candidate_id": (
                        signal.release_candidate_id
                    ),
                    "release_environment": (
                        signal.release_environment
                    ),
                    "kind": signal.kind.value,
                    "generation": signal.generation,
                    "planning_authority": False,
                    "execution_authority": False,
                    "auto_dispatch": False,
                    "release_authority": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except Exception as exc:
        message = (
            str(exc).splitlines()[0].strip()
            if str(exc).strip()
            else type(exc).__name__
        )
        print(
            json.dumps(
                {"ok": False, "error": message[:256]},
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
