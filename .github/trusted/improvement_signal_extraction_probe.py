from __future__ import annotations

import copy
import json
from pathlib import Path

from ade.improvement_signal import (
    ImprovementEvidenceKind,
    ImprovementSignalKind,
)
from ade.improvement_signal_extraction import (
    ImprovementSignalExtractionError,
    extract_actionable_release_gap_signal,
    extract_verified_release_followup_signal,
)


ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_PATH = (
    ROOT
    / ".autodev"
    / "campaign-evidence"
    / "v1.8-autonomous-release-proof-001.json"
)
FINALIZATION_PATH = (
    ROOT
    / ".autodev"
    / "release"
    / "proof"
    / "final"
    / "post-verification-finalization.json"
)
TARGET_PATH = (
    ROOT
    / ".autodev"
    / "release"
    / "proof"
    / "final"
    / "post-verification-target.json"
)


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _base_kwargs():
    return {
        "campaign_evidence_payload": _load(CAMPAIGN_PATH),
        "finalization_payload": _load(FINALIZATION_PATH),
        "target_payload": _load(TARGET_PATH),
        "campaign_evidence_path": (
            ".autodev/campaign-evidence/"
            "v1.8-autonomous-release-proof-001.json"
        ),
        "finalization_path": (
            ".autodev/release/proof/final/"
            "post-verification-finalization.json"
        ),
        "target_path": (
            ".autodev/release/proof/final/"
            "post-verification-target.json"
        ),
    }


def main() -> int:
    try:
        kwargs = _base_kwargs()
        observation = extract_verified_release_followup_signal(
            **kwargs
        )
        if observation.kind is not ImprovementSignalKind.RELEASE_FOLLOWUP:
            raise AssertionError(
                "verified release must produce observation follow-up"
            )
        if observation.source_sha != (
            "726431b60db8b25cdd4bc15bb1493a0060f36327"
        ):
            raise AssertionError("release source SHA drift")
        if observation.release_candidate_id != (
            "release-a4cd075b270b6ad434ae2602"
        ):
            raise AssertionError("release candidate drift")

        gap_payload = {
            "schema_version": 1,
            "repository": observation.repository,
            "source_sha": observation.source_sha,
            "release_candidate_id": (
                observation.release_candidate_id
            ),
            "release_environment": observation.release_environment,
            "signal_kind": ImprovementSignalKind.RUNTIME_GAP.value,
            "detail_fingerprint": "d" * 64,
        }
        runtime_gap = extract_actionable_release_gap_signal(
            **kwargs,
            gap_kind=ImprovementSignalKind.RUNTIME_GAP,
            gap_evidence_kind=ImprovementEvidenceKind.RECOVERY,
            gap_evidence_payload=gap_payload,
            gap_evidence_path=(
                ".autodev/improvement/recovery-gap.json"
            ),
        )
        if runtime_gap.kind is not ImprovementSignalKind.RUNTIME_GAP:
            raise AssertionError("trusted recovery gap kind drift")

        try:
            extract_actionable_release_gap_signal(
                **kwargs,
                gap_kind=ImprovementSignalKind.QUALITY_GAP,
                gap_evidence_kind=(
                    ImprovementEvidenceKind.HUMAN_DECISION
                ),
                gap_evidence_payload={
                    **gap_payload,
                    "signal_kind": (
                        ImprovementSignalKind.QUALITY_GAP.value
                    ),
                },
                gap_evidence_path=(
                    ".autodev/improvement/untrusted-gap.json"
                ),
            )
        except ImprovementSignalExtractionError:
            pass
        else:
            raise AssertionError(
                "successful release alone must not fabricate actionable gap"
            )

        drifted = copy.deepcopy(kwargs["target_payload"])
        drifted["evidence"]["source_sha"] = "f" * 40
        try:
            extract_verified_release_followup_signal(
                **{
                    **kwargs,
                    "target_payload": drifted,
                }
            )
        except ImprovementSignalExtractionError:
            pass
        else:
            raise AssertionError(
                "runtime target source drift must fail closed"
            )

        payload = observation.canonical_dict()
        for field in (
            "planning_authority",
            "execution_authority",
            "auto_dispatch",
            "release_authority",
        ):
            if payload[field] is not False:
                raise AssertionError(
                    f"improvement extraction authority drift: {field}"
                )

        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "proof": (
                        "v1.9-trusted-post-release-feedback-extraction"
                    ),
                    "observation_signal_id": observation.signal_id,
                    "observation_fingerprint": (
                        observation.fingerprint()
                    ),
                    "runtime_gap_signal_id": runtime_gap.signal_id,
                    "runtime_gap_fingerprint": (
                        runtime_gap.fingerprint()
                    ),
                    "release_success_actionable_by_itself": False,
                    "additional_gap_evidence_required": True,
                    "release_identity_bound": True,
                    "runtime_target_identity_bound": True,
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
