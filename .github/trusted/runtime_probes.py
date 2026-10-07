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
_JICHI_INSIGHT_REPOSITORY = "M-Osugi1230/jichi-insight"
_JQUANTS_REPOSITORY = "M-Osugi1230/jquants-research-studio"
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


_JQUANTS_API_IMPORT_SMOKE = r"""
import sys
from pathlib import Path

root = Path.cwd()
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

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
        try:
            completed = subprocess.run(
                [
                    str(workspace.python_executable),
                    "-I",
                    "-c",
                    _JQUANTS_API_IMPORT_SMOKE,
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
                detail_code="jquants-api-import-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="jquants-api-import-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "jquants-api-import-pass"
                if completed.returncode == 0
                else "jquants-api-import-nonzero"
            ),
        )

    return run


def _jquants_vercel_contract_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        validator = workspace.root / "scripts" / "validate_vercel_build_contract.py"
        if not validator.is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jquants-vercel-contract-missing",
            )
        try:
            completed = subprocess.run(
                [str(workspace.python_executable), str(validator)],
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
                detail_code="jquants-vercel-contract-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="jquants-vercel-contract-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "jquants-vercel-contract-pass"
                if completed.returncode == 0
                else "jquants-vercel-contract-nonzero"
            ),
        )

    return run


def _jichi_data_contract_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(invocation: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        validator = workspace.root / "scripts" / "validate_repository.py"
        if not validator.is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-data-validator-missing",
            )
        try:
            completed = subprocess.run(
                [str(workspace.python_executable), str(validator)],
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
                detail_code="jichi-data-validation-timeout",
            )
        except OSError:
            return RuntimeProbeObservation(
                RuntimeProbeStatus.ERROR,
                detail_code="jichi-data-validation-exec-error",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS
            if completed.returncode == 0
            else RuntimeProbeStatus.FAIL,
            detail_code=(
                "jichi-data-validation-pass"
                if completed.returncode == 0
                else "jichi-data-validation-nonzero"
            ),
        )

    return run


def _jichi_next_contract_runner(
    workspace: PreparedRuntimeWorkspace,
):
    def run(_: RuntimeProbeInvocation) -> RuntimeProbeObservation:
        root_package = workspace.root / "package.json"
        web_package = workspace.root / "apps" / "web" / "package.json"
        required_files = (
            workspace.root / "apps" / "web" / "app" / "layout.tsx",
            workspace.root / "apps" / "web" / "app" / "page.tsx",
            workspace.root / "apps" / "web" / "next.config.ts",
            workspace.root / "apps" / "web" / "tsconfig.json",
        )
        if not root_package.is_file() or not web_package.is_file():
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-package-missing",
            )
        if any(not path.is_file() for path in required_files):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-app-contract-missing",
            )
        try:
            root_payload = json.loads(root_package.read_text(encoding="utf-8"))
            web_payload = json.loads(web_package.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-package-invalid",
            )

        root_scripts = root_payload.get("scripts")
        web_scripts = web_payload.get("scripts")
        web_dependencies = web_payload.get("dependencies")
        if not all(
            isinstance(value, dict)
            for value in (root_scripts, web_scripts, web_dependencies)
        ):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-package-contract-invalid",
            )

        required_root_scripts = {"build", "lint", "typecheck", "validate:data", "test:py"}
        required_web_scripts = {"build", "start", "lint", "typecheck"}
        required_dependencies = {"next", "react", "react-dom"}
        if not required_root_scripts.issubset(root_scripts):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-root-scripts-missing",
            )
        if not required_web_scripts.issubset(web_scripts):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-web-scripts-missing",
            )
        if not required_dependencies.issubset(web_dependencies):
            return RuntimeProbeObservation(
                RuntimeProbeStatus.FAIL,
                detail_code="jichi-next-dependencies-missing",
            )
        return RuntimeProbeObservation(
            RuntimeProbeStatus.PASS,
            detail_code="jichi-next-contract-pass",
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
    *,
    target_repository: str | None = None,
) -> TrustedRuntimeProbeRegistry:
    if target_repository == _JQUANTS_REPOSITORY:
        api_runner = (
            _jquants_api_import_runner(workspace)
            if workspace is not None
            else _workspace_not_configured
        )
        vercel_runner = (
            _jquants_vercel_contract_runner(workspace)
            if workspace is not None
            else _workspace_not_configured
        )
        return TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    probe_id="jquants-api-import-smoke",
                    implementation_id="jquants-api-import-smoke-v1",
                    runner=api_runner,
                ),
                RuntimeProbeRegistration(
                    probe_id="jquants-vercel-contract-smoke",
                    implementation_id="jquants-vercel-contract-smoke-v1",
                    runner=vercel_runner,
                ),
            ]
        )
    if target_repository == _JICHI_INSIGHT_REPOSITORY:
        data_runner = (
            _jichi_data_contract_runner(workspace)
            if workspace is not None
            else _workspace_not_configured
        )
        next_runner = (
            _jichi_next_contract_runner(workspace)
            if workspace is not None
            else _workspace_not_configured
        )
        return TrustedRuntimeProbeRegistry(
            [
                RuntimeProbeRegistration(
                    probe_id="jichi-data-contract-smoke",
                    implementation_id="jichi-data-contract-smoke-v1",
                    runner=data_runner,
                ),
                RuntimeProbeRegistration(
                    probe_id="jichi-next-contract-smoke",
                    implementation_id="jichi-next-contract-smoke-v1",
                    runner=next_runner,
                ),
            ]
        )
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
    elif target_repository == _JQUANTS_REPOSITORY:
        required_probe_ids = (
            "jquants-api-import-smoke",
            "jquants-vercel-contract-smoke",
        )
    elif target_repository == _JICHI_INSIGHT_REPOSITORY:
        required_probe_ids = (
            "jichi-data-contract-smoke",
            "jichi-next-contract-smoke",
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
