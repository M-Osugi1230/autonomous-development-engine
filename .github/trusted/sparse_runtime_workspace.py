from __future__ import annotations

import base64
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ade.runtime_verification import RuntimeVerificationContract, RuntimeVerificationError
from runtime_workspace import PreparedRuntimeWorkspace


_MAX_SPARSE_FILES = 8
_MAX_SPARSE_FILE_BYTES = 512 * 1024
_MAX_SPARSE_TOTAL_BYTES = 2 * 1024 * 1024
_MAX_RESPONSE_BYTES = 1024 * 1024


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ADE-Sparse-Runtime-Workspace/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("ADE_TARGET_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _safe_path(path: object) -> str:
    if not isinstance(path, str) or not path.strip():
        raise RuntimeVerificationError("sparse runtime path must be non-empty")
    if path.startswith("/") or "\\" in path:
        raise RuntimeVerificationError("sparse runtime path is unsafe")
    parsed = PurePosixPath(path)
    if ".." in parsed.parts or str(parsed) != path:
        raise RuntimeVerificationError("sparse runtime path must be normalized")
    return path


def _download_file(repository: str, source_sha: str, path: str) -> bytes:
    encoded_path = quote(path, safe="/")
    encoded_sha = quote(source_sha, safe="")
    request = Request(
        (
            f"https://api.github.com/repos/{repository}/contents/"
            f"{encoded_path}?ref={encoded_sha}"
        ),
        headers=_headers(),
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise RuntimeVerificationError(
            f"sparse runtime file fetch failed with HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise RuntimeVerificationError(
            "sparse runtime file fetch failed"
        ) from exc
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise RuntimeVerificationError(
            "sparse runtime file response exceeds trusted budget"
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeVerificationError(
            "sparse runtime file response is invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeVerificationError(
            "sparse runtime file response must be an object"
        )
    if payload.get("type") != "file":
        raise RuntimeVerificationError(
            "sparse runtime target path is not a file"
        )
    size = payload.get("size")
    if type(size) is not int or size < 0 or size > _MAX_SPARSE_FILE_BYTES:
        raise RuntimeVerificationError(
            "sparse runtime file exceeds trusted byte budget"
        )
    if payload.get("encoding") != "base64":
        raise RuntimeVerificationError(
            "sparse runtime file is not base64 encoded"
        )
    encoded = payload.get("content")
    if not isinstance(encoded, str):
        raise RuntimeVerificationError(
            "sparse runtime file content is missing"
        )
    try:
        data = base64.b64decode(encoded.replace("\n", ""), validate=True)
    except ValueError as exc:
        raise RuntimeVerificationError(
            "sparse runtime file contains invalid base64"
        ) from exc
    if len(data) != size or len(data) > _MAX_SPARSE_FILE_BYTES:
        raise RuntimeVerificationError(
            "sparse runtime file size is inconsistent"
        )
    return data


def prepare_sparse_repository_runtime_workspace(
    contract: RuntimeVerificationContract,
    *,
    paths: tuple[str, ...],
) -> PreparedRuntimeWorkspace:
    if not isinstance(contract, RuntimeVerificationContract):
        raise RuntimeVerificationError("contract must be a RuntimeVerificationContract")
    if contract.environment != "repository":
        raise RuntimeVerificationError(
            "sparse repository workspace requires repository environment"
        )
    if not isinstance(paths, tuple) or not paths:
        raise RuntimeVerificationError(
            "sparse repository workspace requires explicit paths"
        )
    if len(paths) > _MAX_SPARSE_FILES:
        raise RuntimeVerificationError(
            "sparse runtime path count exceeds trusted budget"
        )
    normalized = tuple(_safe_path(path) for path in paths)
    if len(set(normalized)) != len(normalized):
        raise RuntimeVerificationError(
            "sparse runtime paths must be unique"
        )

    temp_root = Path(tempfile.mkdtemp(prefix="ade-runtime-sparse-"))
    checkout = temp_root / "checkout"
    checkout.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    try:
        for path in normalized:
            data = _download_file(
                contract.target_repository,
                contract.source_sha,
                path,
            )
            total_bytes += len(data)
            if total_bytes > _MAX_SPARSE_TOTAL_BYTES:
                raise RuntimeVerificationError(
                    "sparse runtime workspace exceeds trusted total byte budget"
                )
            target = checkout.joinpath(*PurePosixPath(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

        fingerprint_payload = {
            "schema_version": 1,
            "mode": "sparse-github-contents",
            "paths": list(normalized),
            "source_sha": contract.source_sha,
        }
        dependency_fingerprint = sha256(
            json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return PreparedRuntimeWorkspace(
            root=checkout,
            python_executable=Path(sys.executable),
            dependency_fingerprint=dependency_fingerprint,
            source_sha=contract.source_sha,
        )
    except RuntimeVerificationError:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise RuntimeVerificationError(
            "sparse runtime workspace preparation failed"
        ) from exc
