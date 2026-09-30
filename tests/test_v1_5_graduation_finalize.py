from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github/trusted/v1_5_graduation_finalize.py"
spec = importlib.util.spec_from_file_location("v1_5_graduation_finalize", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def run(
    *,
    run_id: int,
    name: str,
    event: str,
    conclusion: str,
    head_sha: str,
    created_at: str,
    updated_at: str,
) -> dict:
    return {
        "id": run_id,
        "name": name,
        "event": event,
        "conclusion": conclusion,
        "head_sha": head_sha,
        "created_at": created_at,
        "updated_at": updated_at,
    }


class V15GraduationFinalizeTests(unittest.TestCase):
    def test_select_target_ci_run_binds_exact_head_and_window(self) -> None:
        head = "a" * 40
        rows = [
            run(
                run_id=10,
                name="Phase 1 and 2 checks",
                event="pull_request",
                conclusion="success",
                head_sha="b" * 40,
                created_at="2026-09-30T11:00:00Z",
                updated_at="2026-09-30T11:00:20Z",
            ),
            run(
                run_id=11,
                name="Phase 1 and 2 checks",
                event="pull_request",
                conclusion="success",
                head_sha=head,
                created_at="2026-09-30T11:01:00Z",
                updated_at="2026-09-30T11:01:20Z",
            ),
        ]
        selected = module.select_target_ci_run(
            rows,
            head_sha=head,
            pr_created_at="2026-09-30T11:00:30Z",
            merged_at="2026-09-30T11:02:00Z",
        )
        self.assertEqual(selected["id"], 11)

    def test_select_target_ci_run_fails_closed_without_exact_success(self) -> None:
        with self.assertRaisesRegex(ValueError, "no successful target"):
            module.select_target_ci_run(
                [],
                head_sha="a" * 40,
                pr_created_at="2026-09-30T11:00:30Z",
                merged_at="2026-09-30T11:02:00Z",
            )

    def test_select_remote_gate_run_uses_success_inside_ci_merge_window(self) -> None:
        ci = run(
            run_id=20,
            name="Phase 1 and 2 checks",
            event="pull_request",
            conclusion="success",
            head_sha="a" * 40,
            created_at="2026-09-30T11:00:00Z",
            updated_at="2026-09-30T11:00:40Z",
        )
        rows = [
            run(
                run_id=21,
                name="ADE Remote PR Gate",
                event="workflow_run",
                conclusion="success",
                head_sha="c" * 40,
                created_at="2026-09-30T11:00:45Z",
                updated_at="2026-09-30T11:00:55Z",
            ),
            run(
                run_id=22,
                name="ADE Remote PR Gate",
                event="workflow_run",
                conclusion="failure",
                head_sha="c" * 40,
                created_at="2026-09-30T11:00:50Z",
                updated_at="2026-09-30T11:00:56Z",
            ),
        ]
        selected = module.select_remote_gate_run(
            rows,
            ci_run=ci,
            merged_at="2026-09-30T11:01:00Z",
        )
        self.assertEqual(selected["id"], 21)

    def test_controller_run_rejects_manual_dispatch(self) -> None:
        row = run(
            run_id=30,
            name="ADE Resume Watch",
            event="workflow_dispatch",
            conclusion="success",
            head_sha="d" * 40,
            created_at="2026-09-30T11:00:00Z",
            updated_at="2026-09-30T11:00:01Z",
        )
        with self.assertRaisesRegex(ValueError, "not trusted|manual"):
            module.validate_controller_run(
                row,
                expected_name=("ADE Jules Cycle", "ADE Resume Watch"),
                allow_events=("repository_dispatch", "workflow_run"),
            )


if __name__ == "__main__":
    unittest.main()
