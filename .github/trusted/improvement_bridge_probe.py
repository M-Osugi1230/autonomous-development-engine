from __future__ import annotations

import json

from ade.autonomous_backlog import AutonomousBacklog
from ade.autonomous_backlog_resolution import (
    BacklogResolutionState,
    resolve_autonomous_backlog,
)
from ade.autonomous_backlog_selection import (
    select_next_backlog_candidate,
)
from ade.improvement_bridge import (
    ImprovementBridgeError,
    build_improvement_memory_backlog_bridge,
)
from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementEvidenceRef,
    ImprovementSignalKind,
    build_improvement_signal,
)
from ade.improvement_signal_ledger import ImprovementSignalLedger
from ade.improvement_signal_resolution import (
    ImprovementResolutionState,
    resolve_improvement_signals,
)


REPOSITORY = "M-Osugi1230/one-minute-thought-experiments"
SOURCE_SHA = "726431b60db8b25cdd4bc15bb1493a0060f36327"
RELEASE_ID = "release-a4cd075b270b6ad434ae2602"


def _signal(
    *,
    kind: ImprovementSignalKind,
    statement: str,
    seed: str,
):
    return build_improvement_signal(
        repository=REPOSITORY,
        source_sha=SOURCE_SHA,
        release_candidate_id=RELEASE_ID,
        release_environment="preview",
        kind=kind,
        statement=statement,
        evidence_refs=(
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
            ImprovementEvidenceRef(
                kind=ImprovementEvidenceKind.RECOVERY,
                path=(
                    ".autodev/improvement/recovery-gap.json"
                ),
                fingerprint=("c" if seed != "c" else "d") * 64,
            ),
        ),
        tags=("verified-release",),
    )


def main() -> int:
    try:
        runtime = _signal(
            kind=ImprovementSignalKind.RUNTIME_GAP,
            statement="Investigate one bounded runtime gap.",
            seed="a",
        )
        quality = _signal(
            kind=ImprovementSignalKind.QUALITY_GAP,
            statement="Investigate one bounded quality gap.",
            seed="d",
        )
        ledger = ImprovementSignalLedger(
            signals=(runtime, quality)
        )
        resolution = resolve_improvement_signals(ledger)

        if (
            resolution.entry_for(runtime.signal_id).state
            is not ImprovementResolutionState.CURRENT
        ):
            raise AssertionError("runtime signal must be CURRENT")
        if (
            resolution.entry_for(quality.signal_id).state
            is not ImprovementResolutionState.COOLDOWN
        ):
            raise AssertionError("quality sibling must be COOLDOWN")

        bundle = build_improvement_memory_backlog_bridge(
            ledger=ledger,
            resolution=resolution,
            signal_id=runtime.signal_id,
            signal_path=(
                ".autodev/improvement/signals/"
                + runtime.signal_id
                + ".json"
            ),
            resolution_path=(
                ".autodev/improvement/resolution.json"
            ),
        )
        payload = bundle.canonical_dict()
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "selection_authority",
        ):
            if payload[field] is not False:
                raise AssertionError(
                    f"bridge authority drift: {field}"
                )

        try:
            build_improvement_memory_backlog_bridge(
                ledger=ledger,
                resolution=resolution,
                signal_id=quality.signal_id,
                signal_path=(
                    ".autodev/improvement/signals/"
                    + quality.signal_id
                    + ".json"
                ),
                resolution_path=(
                    ".autodev/improvement/resolution.json"
                ),
            )
        except ImprovementBridgeError:
            pass
        else:
            raise AssertionError(
                "COOLDOWN signal crossed Memory/Backlog bridge"
            )

        backlog = AutonomousBacklog(
            candidates=(bundle.backlog_candidate,)
        )
        backlog_resolution = resolve_autonomous_backlog(
            backlog,
            current_sources={REPOSITORY: SOURCE_SHA},
        )
        if (
            backlog_resolution.entry_for(
                bundle.backlog_candidate.candidate_id
            ).state
            is not BacklogResolutionState.CURRENT
        ):
            raise AssertionError(
                "bridged candidate did not enter normal Backlog resolution"
            )
        selection = select_next_backlog_candidate(
            backlog,
            backlog_resolution,
        )
        if (
            selection.selected_candidate_id
            != bundle.backlog_candidate.candidate_id
        ):
            raise AssertionError(
                "existing Backlog selection did not select candidate"
            )
        if (
            selection.canonical_dict()["planning_goal_authority"]
            is not False
        ):
            raise AssertionError(
                "Backlog selection unexpectedly granted PlanningGoal authority"
            )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-improvement-memory-backlog-bridge"
                    ),
                    "signal_id": bundle.signal_id,
                    "bridge_fingerprint": bundle.fingerprint(),
                    "memory_id": bundle.memory_record.memory_id,
                    "backlog_candidate_id": (
                        bundle.backlog_candidate.candidate_id
                    ),
                    "cooldown_blocked": True,
                    "existing_backlog_resolution_required": True,
                    "existing_backlog_selection_required": True,
                    "planning_authority": False,
                    "execution_authority": False,
                    "auto_dispatch": False,
                    "selection_authority": False,
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
