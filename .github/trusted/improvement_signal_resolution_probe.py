from __future__ import annotations

import json

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import (
    ImprovementResolutionPolicy,
    ImprovementResolutionReason,
    ImprovementResolutionState,
    resolve_improvement_signals,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_ID = "release-a4cd075b270b6ad434ae2602"


def _evidence(seed: str):
    return (
        ImprovementEvidenceRef(
            kind=ImprovementEvidenceKind.RELEASE_EVIDENCE,
            path=(
                ".autodev/campaign-evidence/"
                "v1.8-autonomous-release-proof-001.json"
            ),
            fingerprint=seed * 64,
        ),
        ImprovementEvidenceRef(
            kind=ImprovementEvidenceKind.POST_VERIFICATION,
            path=(
                ".autodev/release/proof/final/"
                "post-verification-finalization.json"
            ),
            fingerprint=("b" if seed != "b" else "c") * 64,
        ),
    )


def _signal(
    *,
    kind: ImprovementSignalKind,
    statement: str,
    seed: str,
    parent_signal_id: str | None = None,
    generation: int = 0,
):
    return build_improvement_signal(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=_evidence(seed),
        parent_signal_id=parent_signal_id,
        generation=generation,
        tags=(kind.value.casefold().replace("_", "-"),),
    )


def main() -> int:
    try:
        observation = _signal(
            kind=ImprovementSignalKind.RELEASE_FOLLOWUP,
            statement="Retain the verified release observation.",
            seed="a",
        )
        runtime = _signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate one bounded runtime gap.",
            seed="c",
        )
        quality = _signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate one bounded quality gap.",
            seed="d",
        )
        performance = _signal(
            kind=ImprovementSignalKind.PERFORMANCE_GAP,
            statement="Investigate one bounded performance gap.",
            seed="e",
        )

        ledger = ImprovementSignalLedger(
            signals=(performance, observation, quality, runtime)
        )
        resolution = resolve_improvement_signals(ledger)

        if (
            resolution.entry_for(observation.signal_id).state
            is not ImprovementResolutionState.OBSERVATION_ONLY
        ):
            raise AssertionError(
                "verified release observation became actionable"
            )
        if (
            resolution.entry_for(runtime.signal_id).state
            is not ImprovementResolutionState.CURRENT
        ):
            raise AssertionError(
                "controller priority did not select runtime gap"
            )
        for signal in (quality, performance):
            if (
                resolution.entry_for(signal.signal_id).state
                is not ImprovementResolutionState.COOLDOWN
            ):
                raise AssertionError(
                    "one-per-release cooldown budget failed"
                )
        if resolution.current_signal_ids != (runtime.signal_id,):
            raise AssertionError("current signal budget drift")

        child = _signal(
            kind=ImprovementSignalKind.RELIABILITY_GAP,
            statement="Investigate one refined reliability gap.",
            seed="f",
            parent_signal_id=runtime.signal_id,
            generation=1,
        )
        successor_resolution = resolve_improvement_signals(
            ImprovementSignalLedger(signals=(runtime, child))
        )
        if (
            successor_resolution.entry_for(runtime.signal_id).state
            is not ImprovementResolutionState.SUPERSEDED
        ):
            raise AssertionError("clear successor did not supersede parent")
        if (
            successor_resolution.entry_for(runtime.signal_id).reason
            is not ImprovementResolutionReason.LINEAGE_ADVANCED
        ):
            raise AssertionError("lineage supersession reason drift")

        sibling = _signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate one competing refined quality gap.",
            seed="1",
            parent_signal_id=runtime.signal_id,
            generation=1,
        )
        conflict_resolution = resolve_improvement_signals(
            ImprovementSignalLedger(
                signals=(runtime, child, sibling)
            )
        )
        for signal in (child, sibling):
            if (
                conflict_resolution.entry_for(signal.signal_id).state
                is not ImprovementResolutionState.CONFLICTED
            ):
                raise AssertionError(
                    "branching lineage did not fail closed"
                )

        chain = [runtime]
        parent = runtime
        seeds = ("2", "3", "4", "5", "6")
        for generation, seed in enumerate(seeds, start=1):
            next_signal = _signal(
                kind=ImprovementSignalKind.RUNTIME_GAP,
                statement=(
                    "Investigate bounded lineage generation "
                    + str(generation)
                    + "."
                ),
                seed=seed,
                parent_signal_id=parent.signal_id,
                generation=generation,
            )
            chain.append(next_signal)
            parent = next_signal

        limited_resolution = resolve_improvement_signals(
            ImprovementSignalLedger(signals=tuple(chain)),
            policy=ImprovementResolutionPolicy(max_generation=4),
        )
        if (
            limited_resolution.entry_for(chain[-1].signal_id).state
            is not ImprovementResolutionState.CYCLE_LIMIT
        ):
            raise AssertionError(
                "recursive improvement generation exceeded trusted budget"
            )

        payload = resolution.canonical_dict()
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
        ):
            if payload[field] is not False:
                raise AssertionError(
                    f"resolution authority drift: {field}"
                )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-continuous-improvement-signal-resolution"
                    ),
                    "ledger_fingerprint": ledger.fingerprint(),
                    "resolution_fingerprint": resolution.fingerprint(),
                    "observation_only": observation.signal_id,
                    "current_signal_id": runtime.signal_id,
                    "cooldown_count": 2,
                    "clear_successor_supersedes_parent": True,
                    "branching_lineage_conflicts": True,
                    "cycle_limit_enforced": True,
                    "max_current_per_release": 1,
                    "planning_authority": False,
                    "execution_authority": False,
                    "auto_dispatch": False,
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
