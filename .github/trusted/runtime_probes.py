from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

from ade.runtime_probe_registry import (
    RuntimeProbeInvocation,
    RuntimeProbeObservation,
    RuntimeProbeRegistration,
    TrustedRuntimeProbeRegistry,
)
from ade.runtime_verification import RuntimeProbeStatus
from ade.runtime_verification_trigger import RuntimeVerificationPolicy
from runtime_workspace import PreparedRuntimeWorkspace


_LEGACY_THOUGHT_PIPELINE_REPOSITORIES = frozenset(
    {"M-Osugi1230/one-minute-thought-experiments"}
)
_MODULE_NAME = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_ATTR_PATH = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")


def _probe_environment(workspace: PreparedRuntimeWorkspace) -> dict[str, str]:
    home = workspace.root.parent / "probe-home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": str(workspace.python_executable.parent),
        "HOME": str(home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join(
            (
                str(workspace.root),
                str(workspace.root / "src"),
            )
        ),
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


def _repository_entrypoint(
    workspace: PreparedRuntimeWorkspace,
) -> tuple[str, str | None] | None:
    pyproject = workspace.root / "pyproject.toml"
    if not pyproject.is_file():
        return None
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    tool = payload.get("tool")
    if isinstance(tool, dict):
        vercel = tool.get("vercel")
        if isinstance(vercel, dict):
            raw = vercel.get("entrypoint")
            if isinstance(raw, str) and raw.strip():
                module, separator, attribute = raw.strip().partition(":")
                if (
                    _MODULE_NAME.fullmatch(module) is not None
                    and (
                        not separator
                        or (
                            attribute
                            and _ATTR_PATH.fullmatch(attribute) is not None
                        )
                    )
                ):
                    return module, attribute or None

    if (workspace.root / "app.py").is_file():
        return "app", None

    project = payload.get("project")
    name = project.get("name") if isinstance(project, dict) else None
    if isinstance(name, str) and name.strip():
        module = name.strip().replace("-", "_")
        if _MODULE_NAME.fullmatch(module) is not None:
            if (workspace.root / module / "__init__.py").is_file():
                return module, None
            if (workspace.root / "src" / module / "__init__.py").is_file():
                return module, None
    return None


def _repository_bytecode_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        try:
            completed = subprocess.run(
                [
                    str(workspace.python_executable),
                    "-I",
                    "-m",
                    "compileall",
                    "-q",
                    str(workspace.root),
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
                detail_code="repository-bytecode-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="repository-bytecode-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "repository-bytecode-pass"
                if completed.returncode == 0
                else "repository-bytecode-nonzero"
            ),
        )

    return run


def _repository_entrypoint_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        entrypoint = _repository_entrypoint(workspace)
        if entrypoint is None:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="repository-entrypoint-missing",
            )
        module_name, attribute_path = entrypoint
        script = (
            "import importlib, sys\n"
            "from pathlib import Path\n"
            "root = Path.cwd()\n"
            "sys.path.insert(0, str(root))\n"
            "sys.path.insert(0, str(root / 'src'))\n"
            f"module = importlib.import_module({json.dumps(module_name)})\n"
            f"attribute_path = {json.dumps(attribute_path)}\n"
            "if attribute_path:\n"
            "    value = module\n"
            "    for part in attribute_path.split('.'):\n"
            "        value = getattr(value, part)\n"
        )
        try:
            completed = subprocess.run(
                [
                    str(workspace.python_executable),
                    "-I",
                    "-c",
                    script,
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
                detail_code="repository-entrypoint-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="repository-entrypoint-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "repository-entrypoint-pass"
                if completed.returncode == 0
                else "repository-entrypoint-nonzero"
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
    bytecode_runner = (
        _repository_bytecode_runner(workspace)
        if workspace is not None
        else _workspace_not_configured
    )
    entrypoint_runner = (
        _repository_entrypoint_runner(workspace)
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
            RuntimeProbeRegistration(
                probe_id="repository-bytecode-smoke",
                implementation_id="repository-bytecode-smoke-v1",
                runner=bytecode_runner,
            ),
            RuntimeProbeRegistration(
                probe_id="repository-entrypoint-smoke",
                implementation_id="repository-entrypoint-smoke-v1",
                runner=entrypoint_runner,
            ),
        ]
    )


def build_runtime_verification_policy(
    target_repository: str,
) -> RuntimeVerificationPolicy:
    if target_repository in _LEGACY_THOUGHT_PIPELINE_REPOSITORIES:
        required_probe_ids = (
            "offline-cli-smoke",
            "production-import-smoke",
        )
    else:
        required_probe_ids = (
            "repository-bytecode-smoke",
            "repository-entrypoint-smoke",
        )
    return RuntimeVerificationPolicy(
        target_repository=target_repository,
        environment="repository",
        required_probe_ids=required_probe_ids,
        max_attempts=2,
        timeout_seconds=300,
    )
