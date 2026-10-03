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


JQUANTS_REPOSITORY = "M-Osugi1230/jquants-research-studio"


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


def _run_command(
    workspace: PreparedRuntimeWorkspace,
    invocation: RuntimeProbeInvocation,
    command: list[str],
    *,
    pass_code: str,
    fail_code: str,
    timeout_code: str,
    error_code: str,
) -> RuntimeProbeObservation:
    try:
        completed = subprocess.run(
            command,
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
            detail_code=timeout_code,
        )
    except OSError:
        return RuntimeProbeObservation(
            RuntimeProbeStatus.ERROR,
            detail_code=error_code,
        )
    return RuntimeProbeObservation(
        RuntimeProbeStatus.PASS
        if completed.returncode == 0
        else RuntimeProbeStatus.FAIL,
        detail_code=pass_code if completed.returncode == 0 else fail_code,
    )


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
        return _run_command(
            workspace,
            invocation,
            [
                str(workspace.python_executable),
                str(pipeline),
                "001",
                "--offline",
            ],
            pass_code="offline-cli-pass",
            fail_code="offline-cli-nonzero",
            timeout_code="offline-cli-timeout",
            error_code="offline-cli-exec-error",
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
        return _run_command(
            workspace,
            invocation,
            [
                str(workspace.python_executable),
                "-I",
                "-c",
                _IMPORT_SMOKE,
            ],
            pass_code="production-import-pass",
            fail_code="production-import-nonzero",
            timeout_code="production-import-timeout",
            error_code="production-import-exec-error",
        )

    return run


_JQUANTS_API_IMPORT_SMOKE = r"""
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root))

try:
    from fastapi import FastAPI
    from app import app
except Exception:
    raise SystemExit(1)

if not isinstance(app, FastAPI):
    raise SystemExit(1)

paths = {getattr(route, "path", None) for route in app.routes}
required = {
    "/health",
    "/health/deep",
    "/research/v2/context",
    "/research/v2/data-status",
}
if not required.issubset(paths):
    raise SystemExit(1)

raise SystemExit(0)
"""


def _jquants_api_import_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        if not (workspace.root / "app.py").is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jquants-api-entrypoint-missing",
            )
        if not (workspace.root / "apps" / "api" / "main.py").is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jquants-api-main-missing",
            )
        return _run_command(
            workspace,
            invocation,
            [
                str(workspace.python_executable),
                "-I",
                "-c",
                _JQUANTS_API_IMPORT_SMOKE,
            ],
            pass_code="jquants-api-import-pass",
            fail_code="jquants-api-import-nonzero",
            timeout_code="jquants-api-import-timeout",
            error_code="jquants-api-import-exec-error",
        )

    return run


def _jquants_vercel_contract_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        validator = (
            workspace.root
            / "scripts"
            / "validate_vercel_build_contract.py"
        )
        if not validator.is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jquants-vercel-contract-missing",
            )
        return _run_command(
            workspace,
            invocation,
            [
                str(workspace.python_executable),
                str(validator),
            ],
            pass_code="jquants-vercel-contract-pass",
            fail_code="jquants-vercel-contract-nonzero",
            timeout_code="jquants-vercel-contract-timeout",
            error_code="jquants-vercel-contract-exec-error",
        )

    return run


def _workspace_not_configured(
    _: RuntimeProbeInvocation,
) -> RuntimeProbeObservation:
    return RuntimeProbeObservation(
        RuntimeProbeStatus.ERROR,
        detail_code="runtime-workspace-not-configured",
    )


def _runner(
    workspace: PreparedRuntimeWorkspace | None,
    factory,
):
    return factory(workspace) if workspace is not None else _workspace_not_configured


def build_runtime_probe_registry(
    workspace: PreparedRuntimeWorkspace | None = None,
    *,
    target_repository: str | None = None,
) -> TrustedRuntimeProbeRegistry:
    if target_repository == JQUANTS_REPOSITORY:
        return TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    probe_id="jquants-api-import-smoke",
                    implementation_id="jquants-api-import-smoke-v1",
                    runner=_runner(workspace, _jquants_api_import_runner),
                ),
                RuntimeProbeRegistration(
                    probe_id="jquants-vercel-contract-smoke",
                    implementation_id="jquants-vercel-contract-smoke-v1",
                    runner=_runner(workspace, _jquants_vercel_contract_runner),
                ),
            ]
        )

    return TrustedRuntimeProbeRegistry(
        [
            RuntimeProbeRegistration(
                probe_id="offline-cli-smoke",
                implementation_id="offline-cli-smoke-v2",
                runner=_runner(workspace, _offline_cli_runner),
            ),
            RuntimeProbeRegistration(
                probe_id="production-import-smoke",
                implementation_id="production-import-smoke-v2",
                runner=_runner(workspace, _production_import_runner),
            ),
        ]
    )


def build_runtime_verification_policy(
    target_repository: str,
) -> RuntimeVerificationPolicy:
    if target_repository == JQUANTS_REPOSITORY:
        required = (
            "jquants-api-import-smoke",
            "jquants-vercel-contract-smoke",
        )
    else:
        required = (
            "offline-cli-smoke",
            "production-import-smoke",
        )
    return RuntimeVerificationPolicy(
        target_repository=target_repository,
        environment="repository",
        required_probe_ids=required,
        max_attempts=2,
        timeout_seconds=300,
    )
