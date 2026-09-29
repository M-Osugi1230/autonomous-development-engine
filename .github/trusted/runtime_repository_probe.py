from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from ade.runtime_probe_executor import execute_runtime_verification_bounded
from ade.runtime_verification import (
    RuntimeVerificationContract,
    RuntimeVerificationDisposition,
)
from runtime_probes import build_runtime_probe_registry
from runtime_workspace import PreparedRuntimeWorkspace


SHA = "a" * 40


def _workspace(root: Path, *, failing_cli: bool = False) -> PreparedRuntimeWorkspace:
    package = root / "src" / "thought_pipeline"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    exit_code = 2 if failing_cli else 0
    (root / "pipeline.py").write_text(
        (
            "from __future__ import annotations\n"
            "import sys\n"
            "expected = ['001', '--offline']\n"
            f"raise SystemExit({exit_code} if sys.argv[1:] == expected else 3)\n"
        ),
        encoding="utf-8",
    )
    return PreparedRuntimeWorkspace(
        root=root,
        python_executable=Path(sys.executable),
        dependency_fingerprint="b" * 64,
        source_sha=SHA,
    )


def _contract() -> RuntimeVerificationContract:
    return RuntimeVerificationContract(
        verification_id="real-repository-runtime-proof",
        target_repository="example/target",
        source_sha=SHA,
        environment="repository",
        required_probe_ids=("offline-cli-smoke", "production-import-smoke"),
        max_attempts=1,
        timeout_seconds=15,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        workspace = _workspace(Path(tmp))
        registry = build_runtime_probe_registry(workspace)
        execution = execute_runtime_verification_bounded(
            _contract(),
            registry,
        )
        assert (
            execution.report.disposition
            is RuntimeVerificationDisposition.VERIFIED
        )
        details = {
            result.probe_id: result.detail_code
            for result in execution.report.results
        }
        assert details == {
            "offline-cli-smoke": "offline-cli-pass",
            "production-import-smoke": "production-import-pass",
        }
        configured_fingerprint = registry.fingerprint()
        unconfigured_fingerprint = build_runtime_probe_registry().fingerprint()
        assert configured_fingerprint == unconfigured_fingerprint

    with tempfile.TemporaryDirectory() as tmp:
        workspace = _workspace(Path(tmp), failing_cli=True)
        failed = execute_runtime_verification_bounded(
            _contract(),
            build_runtime_probe_registry(workspace),
        )
        assert (
            failed.report.disposition
            is RuntimeVerificationDisposition.FAILED
        )

    print(json.dumps({
        "ok": True,
        "offline_cli_executes_real_process": True,
        "production_import_executes_real_process": True,
        "workspace_configuration_does_not_change_registry_fingerprint": True,
        "nonzero_runtime_exit_fails_verification": True,
        "verified_report_fingerprint": execution.report.fingerprint(),
        "failed_report_fingerprint": failed.report.fingerprint(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
