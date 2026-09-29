from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Iterable


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MANIFEST_NAMES = {
    "Cargo.toml",
    "Gemfile",
    "Makefile",
    "composer.json",
    "go.mod",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}
_SOURCE_ROOT_NAMES = {"app", "lib", "packages", "src"}
_TEST_ROOT_NAMES = {"spec", "test", "tests"}


class RepositoryIntelligenceError(ValueError):
    """Trusted repository-structure snapshot validation failed."""


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repository: str
    base_branch: str
    source_sha: str
    paths: tuple[str, ...]
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    manifest_paths: tuple[str, ...]
    workflow_paths: tuple[str, ...]
    documentation_paths: tuple[str, ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "source_sha": self.source_sha,
            "path_count": len(self.paths),
            "paths": list(self.paths),
            "source_roots": list(self.source_roots),
            "test_roots": list(self.test_roots),
            "manifest_paths": list(self.manifest_paths),
            "workflow_paths": list(self.workflow_paths),
            "documentation_paths": list(self.documentation_paths),
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RepositoryPlannerContext:
    payload: dict[str, Any]
    serialized: str
    fingerprint: str


def _normalized_repository(value: str) -> str:
    if not isinstance(value, str) or _REPOSITORY.fullmatch(value) is None:
        raise RepositoryIntelligenceError("repository must be owner/name")
    return value


def _normalized_branch(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > 120
        or _CONTROL.search(value)
    ):
        raise RepositoryIntelligenceError("base_branch is invalid")
    return value.strip()


def _normalized_sha(value: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise RepositoryIntelligenceError("source_sha must be a lowercase 40-char SHA")
    return value


def _normalized_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise RepositoryIntelligenceError("repository path is invalid")
    if value.startswith("/") or "\\" in value or _CONTROL.search(value):
        raise RepositoryIntelligenceError(f"unsafe repository path: {value!r}")
    parsed = PurePosixPath(value)
    if "." in parsed.parts or ".." in parsed.parts or str(parsed) != value:
        raise RepositoryIntelligenceError(f"repository path must be normalized: {value!r}")
    return value


def _root_for(path: str, names: set[str]) -> str | None:
    first = PurePosixPath(path).parts[0]
    return first if first in names else None


def _is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        name in _MANIFEST_NAMES
        or name.startswith("requirements-") and name.endswith(".txt")
    )


def _is_workflow(path: str) -> bool:
    return (
        path.startswith(".github/workflows/")
        and PurePosixPath(path).suffix in {".yml", ".yaml"}
    )


def _is_documentation(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        path.startswith("docs/")
        or p.name.casefold().startswith("readme")
        or p.name.casefold() in {"contributing.md", "architecture.md"}
    )


def build_repository_snapshot(
    *,
    repository: str,
    base_branch: str,
    source_sha: str,
    paths: Iterable[str],
    max_paths: int = 5000,
) -> RepositorySnapshot:
    if type(max_paths) is not int or max_paths < 1 or max_paths > 20000:
        raise RepositoryIntelligenceError("max_paths must be between 1 and 20000")

    normalized: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = _normalized_path(raw)
        if path in seen:
            raise RepositoryIntelligenceError(f"duplicate repository path: {path}")
        seen.add(path)
        normalized.append(path)
        if len(normalized) > max_paths:
            raise RepositoryIntelligenceError("repository tree exceeds trusted path budget")

    ordered = tuple(sorted(normalized))
    source_roots = tuple(
        sorted(
            {
                root
                for path in ordered
                if (root := _root_for(path, _SOURCE_ROOT_NAMES)) is not None
            }
        )
    )
    test_roots = tuple(
        sorted(
            {
                root
                for path in ordered
                if (root := _root_for(path, _TEST_ROOT_NAMES)) is not None
            }
        )
    )

    return RepositorySnapshot(
        repository=_normalized_repository(repository),
        base_branch=_normalized_branch(base_branch),
        source_sha=_normalized_sha(source_sha),
        paths=ordered,
        source_roots=source_roots,
        test_roots=test_roots,
        manifest_paths=tuple(path for path in ordered if _is_manifest(path)),
        workflow_paths=tuple(path for path in ordered if _is_workflow(path)),
        documentation_paths=tuple(path for path in ordered if _is_documentation(path)),
    )


def _path_within(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


def planner_repository_context(
    snapshot: RepositorySnapshot,
    *,
    allowed_path_prefixes: tuple[str, ...],
    max_files: int = 200,
    max_chars: int = 12000,
) -> RepositoryPlannerContext:
    if not isinstance(snapshot, RepositorySnapshot):
        raise RepositoryIntelligenceError("snapshot must be a RepositorySnapshot")
    if type(max_files) is not int or max_files < 1 or max_files > 1000:
        raise RepositoryIntelligenceError("max_files must be between 1 and 1000")
    if type(max_chars) is not int or max_chars < 1024 or max_chars > 50000:
        raise RepositoryIntelligenceError("max_chars must be between 1024 and 50000")
    if not allowed_path_prefixes:
        raise RepositoryIntelligenceError("allowed_path_prefixes must not be empty")

    prefixes: list[str] = []
    for raw in allowed_path_prefixes:
        prefix = _normalized_path(raw.rstrip("/"))
        prefixes.append(prefix)

    matching = [
        path
        for path in snapshot.paths
        if any(_path_within(path, prefix) for prefix in prefixes)
    ]
    selected = matching[:max_files]

    def payload_for(files: list[str]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repository": snapshot.repository,
            "base_branch": snapshot.base_branch,
            "source_sha": snapshot.source_sha,
            "snapshot_fingerprint": snapshot.fingerprint(),
            "source_roots": list(snapshot.source_roots),
            "test_roots": list(snapshot.test_roots),
            "manifest_paths": list(snapshot.manifest_paths),
            "workflow_paths": list(snapshot.workflow_paths),
            "documentation_paths": list(snapshot.documentation_paths),
            "trusted_writable_roots": prefixes,
            "known_files_within_trusted_roots": files,
            "known_file_count_within_trusted_roots": len(matching),
            "known_files_truncated": len(files) < len(matching),
        }

    payload = payload_for(selected)
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    while len(serialized) > max_chars and selected:
        selected.pop()
        payload = payload_for(selected)
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    if len(serialized) > max_chars:
        raise RepositoryIntelligenceError(
            "repository planner context metadata exceeds trusted character budget"
        )

    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return RepositoryPlannerContext(
        payload=payload,
        serialized=serialized,
        fingerprint=fingerprint,
    )
