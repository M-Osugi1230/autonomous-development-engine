from __future__ import annotations

import json

from ade.improvement_observability import (
    ImprovementCycleViewState,
    ImprovementObservabilitySnapshot,
    build_improvement_observability_snapshot,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import resolve_improvement_signals


REPO = "M-Osugi1230/one-minute-thought-experiments"
SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_ID = "release-a4cd075b270b6ad434ae2602"


def _signal(
    kind: ImprovementSignalKind,
    *,
    seed: str,
    statement: str,
):
    return build_improvement_signal(
        repository=REPO,
        source_sha=SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=(
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
                path=".autodev/release-evidence.json",
                fingerprint=seed * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.POST_VERIFICATION,
                path=".autodev/post-verification.json",
                fingerprint=("b" if seed != "b" else "c") * 64,
            ),
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RECOVERY,
                path=".autodev/recovery-evidence.json",
                fingerprint=("c" if seed != "c" else "d") * 64,
            ),
        ),
        tags=("verified-release",),
    )


def main() -> int:
    try:
        runtime = _signal(
            ImprovementSignalKind.RUNTIME_GAP,
            seed="a",
            statement="Investigate one bounded runtime gap.",
        )
        quality = _signal(
            ImprovementSignalKind.QUALITY_GAP,
            seed="d",
            statement="Investigate one bounded quality gap.",
        )
        ledger = ImprovementSignalLedger(
            signals=(runtime, quality)
        )
        resolution = resolve_improvement_signals(ledger)
        snapshot = build_improvement_observability_snapshot(
            ledger=ledger,
            resolution=resolution,
            release_candidate_id=RELEASE_ID,
        )
        if (
            snapshot.signal_count != 2
            or snapshot.current_count != 1
            or snapshot.cooldown_count != 1
            or snapshot.current_signal_id != runtime.signal_id
            or snapshot.current_signal_kind
            != ImprovementSignalKind.RUNTIME_GAP.value
            or snapshot.cycle_state
            is not ImprovementCycleViewState.NOT_STARTED
        ):
            raise AssertionError(
                "safe improvement observability projection drift"
            )

        payload = snapshot.canonical_dict()
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        forbidden = (
            "statement",
            "evidence_refs",
            "evidence_paths",
            "detail_fingerprint",
            "provider_session",
            "registry_fingerprint",
            "decision_context",
            "raw_telemetry",
            "github_pat_",
            "ghp_",
            "bearer ",
        )
        leaked = [item for item in forbidden if item in serialized]
        if leaked:
            raise AssertionError(
                "unsafe improvement observability fields leaked: "
                + ",".join(leaked)
            )

        if (
            ImprovementObservabilitySnapshot.from_dict(payload)
            != snapshot
        ):
            raise AssertionError(
                "improvement observability round-trip drift"
            )

        tampered = dict(payload)
        tampered["raw_telemetry"] = "private"
        try:
            ImprovementObservabilitySnapshot.from_dict(tampered)
        except ValueError:
            pass
        else:
            raise AssertionError(
                "unknown raw observability field did not fail closed"
            )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-mission-control-improvement-observability"
                    ),
                    "release_candidate_id": (
                        snapshot.release_candidate_id
                    ),
                    "signal_count": snapshot.signal_count,
                    "current_count": snapshot.current_count,
                    "cooldown_count": snapshot.cooldown_count,
                    "cycle_state": snapshot.cycle_state.value,
                    "raw_signal_text_exposed": False,
                    "raw_telemetry_exposed": False,
                    "provider_session_exposed": False,
                    "evidence_paths_exposed": False,
                    "credentials_exposed": False,
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
