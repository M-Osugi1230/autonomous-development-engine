from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from ade.decision_store import DecisionStore
from ade.decisions import DecisionResponse


TRUSTED_DIR = Path(__file__).resolve().parents[1] / ".github" / "trusted"


def load_module():
    trusted = str(TRUSTED_DIR)
    if trusted not in sys.path:
        sys.path.insert(0, trusted)
    path = TRUSTED_DIR / "v1_8_release_proof_prepare.py"
    spec = importlib.util.spec_from_file_location(
        "trusted_v1_8_release_proof_prepare_test",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load v1.8 release proof module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class V18ReleaseProofPrepareTests(unittest.TestCase):
    def test_verified_v17_campaign_prepares_exact_preview_human_wait(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "decisions.json"
            bundle = module.build_release_proof(
                decision_store_path=store_path,
            )

            state = bundle["proof_state"]
            self.assertEqual(
                state["proof_id"],
                "v1.8-autonomous-release-proof-001",
            )
            self.assertEqual(state["state"], "HUMAN_WAIT")
            self.assertEqual(
                state["target_repository"],
                "M-Osugi1230/one-minute-thought-experiments",
            )
            self.assertEqual(
                state["source_sha"],
                "726431b60db8b25cdd4bc15bb1493a0060f36327",
            )
            self.assertEqual(
                state["target_environment"],
                "preview",
            )
            self.assertEqual(
                state["approval_disposition"],
                "HUMAN_WAIT",
            )
            self.assertTrue(
                state["explicit_human_approval_required"]
            )
            self.assertFalse(
                state["external_side_effect_executed"]
            )
            self.assertFalse(state["deployment_authority"])
            self.assertFalse(state["promotion_authority"])
            self.assertFalse(state["auto_promote"])

            store = DecisionStore(store_path)
            open_records = store.list_open()
            self.assertEqual(len(open_records), 1)
            self.assertEqual(
                open_records[0].decision_id,
                state["decision_id"],
            )
            self.assertEqual(
                open_records[0].request.options,
                ("approve", "reject"),
            )

            self.assertEqual(
                bundle["candidate"]["source_sha"],
                state["source_sha"],
            )
            self.assertEqual(
                bundle["candidate"]["target_environment"],
                "preview",
            )
            self.assertIsNone(
                bundle["transition"]["from_environment"]
            )
            self.assertEqual(
                bundle["transition"]["to_environment"],
                "preview",
            )
            self.assertEqual(
                bundle["mission_control"]["promotion_state"],
                "AWAITING_APPROVAL",
            )
            self.assertEqual(
                bundle["mission_control"][
                    "next_required_human_action"
                ],
                "review-release-promotion-approval",
            )

    def test_only_explicit_approve_changes_prepared_state_to_approved(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "decisions.json"
            waiting = module.build_release_proof(
                decision_store_path=store_path,
            )
            decision_id = waiting["proof_state"]["decision_id"]
            store = DecisionStore(store_path)
            store.resolve(
                decision_id,
                DecisionResponse(
                    decision_id=decision_id,
                    text="Approve exact v1.8 preview promotion.",
                    selected_option="approve",
                ),
            )

            approved = module.build_release_proof(
                decision_store_path=store_path,
            )
            state = approved["proof_state"]
            self.assertEqual(state["state"], "APPROVED")
            self.assertEqual(
                state["approval_disposition"],
                "APPROVED",
            )
            self.assertFalse(
                state["external_side_effect_executed"]
            )
            self.assertEqual(
                approved["mission_control"]["promotion_state"],
                "APPROVED",
            )
            self.assertIsNone(
                approved["mission_control"][
                    "next_required_human_action"
                ]
            )

    def test_free_text_without_selected_option_cannot_approve(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "decisions.json"
            waiting = module.build_release_proof(
                decision_store_path=store_path,
            )
            decision_id = waiting["proof_state"]["decision_id"]
            store = DecisionStore(store_path)
            store.resolve(
                decision_id,
                DecisionResponse(
                    decision_id=decision_id,
                    text="Looks good.",
                    selected_option=None,
                ),
            )

            with self.assertRaisesRegex(
                ValueError,
                "explicit approve or reject option",
            ):
                module.build_release_proof(
                    decision_store_path=store_path,
                )


if __name__ == "__main__":
    unittest.main()
