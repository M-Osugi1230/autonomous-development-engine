from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.request import Request, urlopen

from ade.runtime_verification import RuntimeVerificationContract, RuntimeVerificationError


_MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 60 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 5000
_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*\])?(?:[<>=!~].*)?$")


@dataclass(frozen=True, slots=True)
class PreparedRuntimeWorkspace:
    root: Path
    python_executable: Path
    dependency_fingerprint: str
    source_sha: str

    def cleanup(self) -> None:
        shutil.rmtree(self.root.parent, ignore_errors=True)


def _safe_dependency_specs(root: Path) -> tuple[str, ...]:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise RuntimeVerificationError("runtime target has no pyproject.toml")
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise RuntimeVerificationError("runtime target pyproject has no project table")
    raw = project.get("dependencies", [])
    if not isinstance(raw, list):
        raise RuntimeVerificationError("runtime target dependencies must be a list")

    dependencies: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item or len(item) > 200:
            raise RuntimeVerificationError("runtime target dependency spec is invalid")
        if any(token in item for token in ("@", "/", "\\", ";", ":", "\n", "\r", "\t", " ")):
            raise RuntimeVerificationError("runtime target dependency spec is not simple PyPI")
        if _REQUIREMENT.fullmatch(item) is None:
            raise RuntimeVerificationError("runtime target dependency spec is not allowlisted")
        dependencies.append(item)
    return tuple(sorted(dependencies))


def _download_archive(repository: str, source_sha: str) -> bytes:
    url = f"https://api.github.com/repos/{repository}/tarball/{source_sha}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ADE-Runtime-Workspace/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urlopen(request, timeout=60) as response:
        data = response.read(_MAX_ARCHIVE_BYTES + 1)
    if len(data) > _MAX_ARCHIVE_BYTES:
        raise RuntimeVerificationError("runtime target archive exceeds trusted download budget")
    return data


def _extract_archive(data: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > _MAX_ARCHIVE_MEMBERS:
            raise RuntimeVerificationError("runtime target archive member budget exceeded")

        root_names: set[str] = set()
        total_bytes = 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise RuntimeVerificationError("runtime target archive contains unsafe path")
            root_names.add(path.parts[0])
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeVerificationError("runtime target archive contains unsupported links/devices")
            if member.isfile():
                total_bytes += member.size
                if total_bytes > _MAX_EXTRACTED_BYTES:
                    raise RuntimeVerificationError("runtime target archive exceeds extracted byte budget")
        if len(root_names) != 1:
            raise RuntimeVerificationError("runtime target archive has ambiguous root")
        archive_root = next(iter(root_names))

        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            parts = PurePosixPath(member.name).parts
            relative = PurePosixPath(*parts[1:])
            if not relative.parts:
                continue
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeVerificationError("runtime target archive file is unreadable")
            with source, target.open("wb") as out:
                shutil.copyfileobj(source, out)


def _safe_subprocess_env(home: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    return env


def prepare_repository_runtime_workspace(
    contract: RuntimeVerificationContract,
) -> PreparedRuntimeWorkspace:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError("contract must be a RuntimeVerificationContract")
    if contract.environment != "repository":
        raise RuntimeVerificationError("repository runtime workspace requires repository environment")

    temp_root = Path(tempfile.mkdtemp(prefix="ade-runtime-"))
    checkout = temp_root / "checkout"
    home = temp_root / "home"
    venv = temp_root / "venv"
    home.mkdir(parents=True, exist_ok=True)

    try:
        archive = _download_archive(contract.target_repository, contract.source_sha)
        _extract_archive(archive, checkout)
        dependencies = _safe_dependency_specs(checkout)

        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=90,
            env=_safe_subprocess_env(home),
        )
        runtime_python = venv / "bin" / "python"
        if not runtime_python.is_file():
            raise RuntimeVerificationError("runtime venv python was not created")

        if dependencies:
            subprocess.run(
                [
                    str(runtime_python),
                    "-m",
                    "pip",
                    "install",
                    "--only-binary=:all:",
                    *dependencies,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=240,
                env=_safe_subprocess_env(home),
            )

        dep_raw = json.dumps(dependencies, separators=(",", ":"))
        return PreparedRuntimeWorkspace(
            root=checkout,
            python_executable=runtime_python,
            dependency_fingerprint=sha256(dep_raw.encode("utf-8")).hexdigest(),
            source_sha=contract.source_sha,
        )
    except RuntimeVerificationError:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeVerificationError(
            "runtime workspace preparation failed"
        ) from exc
