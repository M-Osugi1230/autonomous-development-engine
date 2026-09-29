from __future__ import annotations

import os
from pathlib import Path
import subprocess

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus
from ade.runtime_verification_trigger import RuntimeVerificationPolicy
from runtime_workspace import PreparedRuntimeWorkspace


def _probe_environment(workspace: PreparedRuntimeWorkspace) -> dict[str, str]:
    home = workspace.root.parent / "probe-home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": str(workspace.python_executable.parent),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(workspace.root / "src"),
        "ADE_RUNTIME_CREDENTIAL_AUTHORITY": "none",
        "ADE_RUNTIME_NETWORK_AUTHORITY": "none",
        "ADE_RUNTIME_DEPLOYMENT_AUTHORITY": "none",
    }


def _command_timeout(invocation: RuntimeProbeInvocation) -> int:
    return max(1, min(invocation.timeout_seconds - 2, 180))


def _offline_cli_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        pipeline = workspace.root / "pipeline.py"
        if not pipeline.is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="offline-cli-entrypoint-missing",
            )
        try:
            completed = subprocess.run(
                [
                    str(workspace.python_executable),
                    str(pipeline),
                    "001",
                    "--offline",
                ],
                cwd=workspace.root,
                env=_probe_environment(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_command_timeout(invocation),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="offline-cli-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="offline-cli-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "offline-cli-pass"
                if completed.returncode == 0
                else "offline-cli-nonzero"
            ),
        )

    return run


_IMPORT_SMOKE = r"""
import importlib
import pkgutil
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root / "src"))

try:
    import thought_pipeline
except Exception:
    raise SystemExit(1)

for module in pkgutil.walk_packages(
    thought_pipeline.__path__,
    thought_pipeline.__name__ + ".",
):
    try:
        importlib.import_module(module.name)
    except Exception:
        raise SystemExit(1)

raise SystemExit(0)
"""


def _production_import_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        if not (workspace.root / "src" / "thought_pipeline").is_dir():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="production-package-missing",
            )
        try:
            completed = subprocess.run(
                [
                    str(workspace.python_executable),
                    "-I",
                    "-c",
                    _IMPORT_SMOKE,
                ],
                cwd=workspace.root,
                env=_probe_environment(workspace),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_command_timeout(invocation),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="production-import-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="production-import-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "production-import-pass"
                if completed.returncode == 0
                else "production-import-nonzero"
            ),
        )

    return run


def _workspace_not_configured(
    _: RuntimeProbeInvocation,
) -> RuntimeProbeObservation:
    return RuntimeProbeObservation(
        RuntimeProbeStatus.ERROR,
        detail_code="runtime-workspace-not-configured",
    )


def build_runtime_probe_registry(
    workspace: PreparedRuntimeWorkspace | None = None,
) -> TrustedRuntimeProbeRegistry:
    offline_runner = (
        _offline_cli_runner(workspace)
        if workspace is not None
        else _workspace_not_configured
    )
    import_runner = (
        _production_import_runner(workspace)
        if workspace is not None
        else _workspace_not_configured
    )
    return TrustedRuntimeProbeRegistry(
        [
            RuntimeProbeRegistration(
                probe_id="offline-cli-smoke",
                implementation_id="offline-cli-smoke-v2",
                runner=offline_runner,
            ),
            RuntimeProbeRegistration(
                probe_id="production-import-smoke",
                implementation_id="production-import-smoke-v2",
                runner=import_runner,
            ),
        ]
    )


def build_runtime_verification_policy(
    target_repository: str,
) -> RuntimeVerificationPolicy:
    return RuntimeVerificationPolicy(
        target_repository=target_repository,
        environment="repository",
        required_probe_ids=(
            "offline-cli-smoke",
            "production-import-smoke",
        ),
        max_attempts=2,
        timeout_seconds=300,
    )
