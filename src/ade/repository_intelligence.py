from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import ast
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


@dataclass(frozen=True, slots=True)
class RepositorySymbol:
    kind: str
    name: str

    def canonical_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name}


@dataclass(frozen=True, slots=True)
class PythonModuleSummary:
    path: str
    module: str
    is_test: bool
    parse_ok: bool
    content_sha: str
    byte_count: int
    symbols: tuple[RepositorySymbol, ...]
    imports: tuple[str, ...]

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "module": self.module,
            "is_test": self.is_test,
            "parse_ok": self.parse_ok,
            "content_sha": self.content_sha,
            "byte_count": self.byte_count,
            "symbols": [symbol.canonical_dict() for symbol in self.symbols],
            "imports": list(self.imports),
        }


@dataclass(frozen=True, slots=True)
class RepositoryContentSummary:
    modules: tuple[PythonModuleSummary, ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "module_count": len(self.modules),
            "modules": [module.canonical_dict() for module in self.modules],
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
class RepositoryDependencyEdge:
    source_path: str
    target_path: str
    kind: str = "import"

    def canonical_dict(self) -> dict[str, str]:
        return {
            "source_path": self.source_path,
            "target_path": self.target_path,
            "kind": self.kind,
        }


@dataclass(frozen=True, slots=True)
class RepositoryTestSourceLink:
    test_path: str
    source_path: str
    reason: str

    def canonical_dict(self) -> dict[str, str]:
        return {
            "test_path": self.test_path,
            "source_path": self.source_path,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RepositoryRelationshipGraph:
    dependency_edges: tuple[RepositoryDependencyEdge, ...]
    test_source_links: tuple[RepositoryTestSourceLink, ...]
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "dependency_edge_count": len(self.dependency_edges),
            "dependency_edges": [
                edge.canonical_dict() for edge in self.dependency_edges
            ],
            "test_source_link_count": len(self.test_source_links),
            "test_source_links": [
                link.canonical_dict() for link in self.test_source_links
            ],
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
class RepositoryImpactEntry:
    path: str
    distance: int
    reason: str
    via_path: str | None
    is_test: bool

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "distance": self.distance,
            "reason": self.reason,
            "via_path": self.via_path,
            "is_test": self.is_test,
        }


@dataclass(frozen=True, slots=True)
class RepositoryImpactAnalysis:
    changed_paths: tuple[str, ...]
    affected_paths: tuple[str, ...]
    affected_test_paths: tuple[str, ...]
    entries: tuple[RepositoryImpactEntry, ...]
    truncated: bool
    schema_version: int = 1

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "changed_paths": list(self.changed_paths),
            "affected_paths": list(self.affected_paths),
            "affected_test_paths": list(self.affected_test_paths),
            "entries": [entry.canonical_dict() for entry in self.entries],
            "truncated": self.truncated,
        }

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.canonical_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def python_candidate_paths(
    snapshot: RepositorySnapshot,
    *,
    allowed_path_prefixes: tuple[str, ...],
    max_files: int = 40,
) -> tuple[str, ...]:
    if not isinstance(snapshot, RepositorySnapshot):
        raise RepositoryIntelligenceError("snapshot must be a RepositorySnapshot")
    if type(max_files) is not int or max_files < 1 or max_files > 200:
        raise RepositoryIntelligenceError("max_files must be between 1 and 200")
    if not allowed_path_prefixes:
        raise RepositoryIntelligenceError("allowed_path_prefixes must not be empty")

    prefixes = tuple(_normalized_path(raw.rstrip("/")) for raw in allowed_path_prefixes)
    candidates = [
        path
        for path in snapshot.paths
        if path.endswith(".py")
        and any(_path_within(path, prefix) for prefix in prefixes)
    ]
    return tuple(candidates[:max_files])


def _python_module_name(path: str) -> str:
    parsed = PurePosixPath(path)
    parts = list(parsed.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or parsed.stem


def _is_test_path(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        parsed.parts[0] in _TEST_ROOT_NAMES
        or parsed.name.startswith("test_")
        or parsed.name.endswith("_test.py")
    )


def _import_name(node: ast.ImportFrom) -> tuple[str, ...]:
    prefix = "." * node.level
    if node.module:
        return (prefix + node.module,)
    values = []
    for alias in node.names:
        if alias.name != "*":
            values.append(prefix + alias.name)
    return tuple(values)


def analyze_python_source(
    *,
    path: str,
    source: str,
    content_sha: str,
    max_source_chars: int = 100000,
    max_symbols: int = 100,
    max_imports: int = 100,
) -> PythonModuleSummary:
    normalized_path = _normalized_path(path)
    if not normalized_path.endswith(".py"):
        raise RepositoryIntelligenceError("python summary path must end with .py")
    if not isinstance(source, str):
        raise RepositoryIntelligenceError("python source must be text")
    if type(max_source_chars) is not int or max_source_chars < 1 or max_source_chars > 500000:
        raise RepositoryIntelligenceError("max_source_chars must be between 1 and 500000")
    if len(source) > max_source_chars:
        raise RepositoryIntelligenceError("python source exceeds trusted character budget")
    if type(max_symbols) is not int or not 1 <= max_symbols <= 500:
        raise RepositoryIntelligenceError("max_symbols must be between 1 and 500")
    if type(max_imports) is not int or not 1 <= max_imports <= 500:
        raise RepositoryIntelligenceError("max_imports must be between 1 and 500")
    _normalized_sha(content_sha)

    byte_count = len(source.encode("utf-8"))
    try:
        tree = ast.parse(source, filename=normalized_path)
    except SyntaxError:
        return PythonModuleSummary(
            path=normalized_path,
            module=_python_module_name(normalized_path),
            is_test=_is_test_path(normalized_path),
            parse_ok=False,
            content_sha=content_sha,
            byte_count=byte_count,
            symbols=(),
            imports=(),
        )

    symbols: list[RepositorySymbol] = []
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append(RepositorySymbol(kind="function", name=node.name))
        elif isinstance(node, ast.ClassDef):
            symbols.append(RepositorySymbol(kind="class", name=node.name))
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(_import_name(node))

    ordered_symbols = tuple(
        sorted(
            {symbol for symbol in symbols},
            key=lambda item: (item.kind, item.name),
        )[:max_symbols]
    )
    ordered_imports = tuple(sorted(set(imports))[:max_imports])

    return PythonModuleSummary(
        path=normalized_path,
        module=_python_module_name(normalized_path),
        is_test=_is_test_path(normalized_path),
        parse_ok=True,
        content_sha=content_sha,
        byte_count=byte_count,
        symbols=ordered_symbols,
        imports=ordered_imports,
    )


def build_python_content_summary(
    files: Iterable[tuple[str, str, str]],
    *,
    max_files: int = 40,
    max_source_chars: int = 100000,
) -> RepositoryContentSummary:
    if type(max_files) is not int or not 1 <= max_files <= 200:
        raise RepositoryIntelligenceError("max_files must be between 1 and 200")

    summaries: list[PythonModuleSummary] = []
    seen: set[str] = set()
    for raw_path, source, content_sha in files:
        path = _normalized_path(raw_path)
        if path in seen:
            raise RepositoryIntelligenceError(f"duplicate content-summary path: {path}")
        seen.add(path)
        summaries.append(
            analyze_python_source(
                path=path,
                source=source,
                content_sha=content_sha,
                max_source_chars=max_source_chars,
            )
        )
        if len(summaries) > max_files:
            raise RepositoryIntelligenceError("content summary exceeds trusted file budget")

    return RepositoryContentSummary(
        modules=tuple(sorted(summaries, key=lambda item: item.path))
    )


def _resolve_import_module(
    *,
    current: PythonModuleSummary,
    imported: str,
) -> str:
    if not imported.startswith("."):
        return imported

    level = len(imported) - len(imported.lstrip("."))
    suffix = imported[level:]
    current_parts = current.module.split(".") if current.module else []
    if PurePosixPath(current.path).name == "__init__.py":
        package_parts = current_parts
    else:
        package_parts = current_parts[:-1]

    ascend = level - 1
    if ascend > len(package_parts):
        return ""
    base = package_parts[: len(package_parts) - ascend] if ascend else package_parts
    if suffix:
        base = [*base, *suffix.split(".")]
    return ".".join(part for part in base if part)


def build_repository_relationships(
    content_summary: RepositoryContentSummary,
) -> RepositoryRelationshipGraph:
    if not isinstance(content_summary, RepositoryContentSummary):
        raise RepositoryIntelligenceError(
            "content_summary must be a RepositoryContentSummary"
        )

    by_module = {
        module.module: module
        for module in content_summary.modules
        if module.module
    }
    edges: set[RepositoryDependencyEdge] = set()
    for module in content_summary.modules:
        if not module.parse_ok:
            continue
        for imported in module.imports:
            resolved = _resolve_import_module(current=module, imported=imported)
            target = by_module.get(resolved)
            if target is None or target.path == module.path:
                continue
            edges.add(
                RepositoryDependencyEdge(
                    source_path=module.path,
                    target_path=target.path,
                )
            )

    links: dict[tuple[str, str], RepositoryTestSourceLink] = {}
    modules_by_stem: dict[str, list[PythonModuleSummary]] = {}
    for module in content_summary.modules:
        if module.is_test:
            continue
        modules_by_stem.setdefault(PurePosixPath(module.path).stem, []).append(module)

    for edge in edges:
        source = next(
            (module for module in content_summary.modules if module.path == edge.source_path),
            None,
        )
        target = next(
            (module for module in content_summary.modules if module.path == edge.target_path),
            None,
        )
        if source is None or target is None or not source.is_test or target.is_test:
            continue
        links[(source.path, target.path)] = RepositoryTestSourceLink(
            test_path=source.path,
            source_path=target.path,
            reason="import",
        )

    for module in content_summary.modules:
        if not module.is_test:
            continue
        stem = PurePosixPath(module.path).stem
        if stem.startswith("test_"):
            source_stem = stem.removeprefix("test_")
        elif stem.endswith("_test"):
            source_stem = stem.removesuffix("_test")
        else:
            continue
        candidates = modules_by_stem.get(source_stem, [])
        if len(candidates) != 1:
            continue
        target = candidates[0]
        key = (module.path, target.path)
        links.setdefault(
            key,
            RepositoryTestSourceLink(
                test_path=module.path,
                source_path=target.path,
                reason="filename",
            ),
        )

    return RepositoryRelationshipGraph(
        dependency_edges=tuple(
            sorted(
                edges,
                key=lambda edge: (edge.source_path, edge.target_path, edge.kind),
            )
        ),
        test_source_links=tuple(
            sorted(
                links.values(),
                key=lambda link: (link.test_path, link.source_path, link.reason),
            )
        ),
    )


def analyze_repository_impact(
    relationship_graph: RepositoryRelationshipGraph,
    *,
    changed_paths: Iterable[str],
    max_depth: int = 3,
    max_results: int = 100,
) -> RepositoryImpactAnalysis:
    if not isinstance(relationship_graph, RepositoryRelationshipGraph):
        raise RepositoryIntelligenceError(
            "relationship_graph must be a RepositoryRelationshipGraph"
        )
    if type(max_depth) is not int or not 0 <= max_depth <= 8:
        raise RepositoryIntelligenceError("max_depth must be between 0 and 8")
    if type(max_results) is not int or not 1 <= max_results <= 500:
        raise RepositoryIntelligenceError("max_results must be between 1 and 500")

    normalized_changed: list[str] = []
    seen: set[str] = set()
    for raw in changed_paths:
        path = _normalized_path(raw)
        if path in seen:
            continue
        seen.add(path)
        normalized_changed.append(path)
        if len(normalized_changed) > 32:
            raise RepositoryIntelligenceError(
                "impact analysis exceeds trusted changed-path budget"
            )
    if not normalized_changed:
        raise RepositoryIntelligenceError("impact analysis requires changed_paths")
    normalized_changed.sort()
    if max_results < len(normalized_changed):
        raise RepositoryIntelligenceError(
            "max_results must fit every changed path"
        )

    reverse: dict[str, set[str]] = {}
    for edge in relationship_graph.dependency_edges:
        reverse.setdefault(edge.target_path, set()).add(edge.source_path)

    distance: dict[str, int] = {path: 0 for path in normalized_changed}
    via: dict[str, str | None] = {path: None for path in normalized_changed}
    reason: dict[str, str] = {path: "changed" for path in normalized_changed}
    queue = deque(normalized_changed)

    while queue:
        current = queue.popleft()
        current_distance = distance[current]
        if current_distance >= max_depth:
            continue
        for dependent in sorted(reverse.get(current, ())):
            candidate_distance = current_distance + 1
            previous_distance = distance.get(dependent)
            previous_via = via.get(dependent)
            should_update = (
                previous_distance is None
                or candidate_distance < previous_distance
                or (
                    candidate_distance == previous_distance
                    and (
                        previous_via is None
                        or current < previous_via
                    )
                )
            )
            if not should_update:
                continue
            distance[dependent] = candidate_distance
            via[dependent] = current
            reason[dependent] = "reverse-import"
            queue.append(dependent)

    for link in relationship_graph.test_source_links:
        source_distance = distance.get(link.source_path)
        if source_distance is None:
            continue
        candidate_distance = source_distance + 1
        if candidate_distance > max_depth + 1:
            continue
        previous_distance = distance.get(link.test_path)
        if (
            previous_distance is None
            or candidate_distance < previous_distance
            or candidate_distance == previous_distance
        ):
            distance[link.test_path] = candidate_distance
            via[link.test_path] = link.source_path
            reason[link.test_path] = "test-source-link"

    all_entries = [
        RepositoryImpactEntry(
            path=path,
            distance=distance[path],
            reason=reason[path],
            via_path=via[path],
            is_test=_is_test_path(path),
        )
        for path in distance
    ]
    ordered = sorted(all_entries, key=lambda entry: (entry.distance, entry.path))
    selected = tuple(ordered[:max_results])
    selected_paths = {entry.path for entry in selected}
    affected = tuple(
        entry.path
        for entry in selected
        if entry.distance > 0
    )
    affected_tests = tuple(
        entry.path
        for entry in selected
        if entry.distance > 0 and entry.is_test
    )

    return RepositoryImpactAnalysis(
        changed_paths=tuple(
            path for path in normalized_changed if path in selected_paths
        ),
        affected_paths=affected,
        affected_test_paths=affected_tests,
        entries=selected,
        truncated=len(selected) < len(ordered),
    )


def planner_repository_context(
    snapshot: RepositorySnapshot,
    *,
    allowed_path_prefixes: tuple[str, ...],
    content_summary: RepositoryContentSummary | None = None,
    relationship_graph: RepositoryRelationshipGraph | None = None,
    max_files: int = 200,
    max_summary_modules: int = 20,
    max_relationships: int = 100,
    max_chars: int = 12000,
) -> RepositoryPlannerContext:
    if not isinstance(snapshot, RepositorySnapshot):
        raise RepositoryIntelligenceError("snapshot must be a RepositorySnapshot")
    if type(max_files) is not int or max_files < 1 or max_files > 1000:
        raise RepositoryIntelligenceError("max_files must be between 1 and 1000")
    if type(max_summary_modules) is not int or not 0 <= max_summary_modules <= 100:
        raise RepositoryIntelligenceError("max_summary_modules must be between 0 and 100")
    if content_summary is not None and not isinstance(
        content_summary, RepositoryContentSummary
    ):
        raise RepositoryIntelligenceError(
            "content_summary must be a RepositoryContentSummary or null"
        )
    if relationship_graph is not None and not isinstance(
        relationship_graph, RepositoryRelationshipGraph
    ):
        raise RepositoryIntelligenceError(
            "relationship_graph must be a RepositoryRelationshipGraph or null"
        )
    if type(max_relationships) is not int or not 0 <= max_relationships <= 500:
        raise RepositoryIntelligenceError(
            "max_relationships must be between 0 and 500"
        )
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
    summary_modules = (
        list(content_summary.modules[:max_summary_modules])
        if content_summary is not None
        else []
    )
    dependency_edges = (
        list(relationship_graph.dependency_edges[:max_relationships])
        if relationship_graph is not None
        else []
    )
    test_source_links = (
        list(relationship_graph.test_source_links[:max_relationships])
        if relationship_graph is not None
        else []
    )

    def payload_for(
        files: list[str],
        modules: list[PythonModuleSummary],
        edges: list[RepositoryDependencyEdge],
        links: list[RepositoryTestSourceLink],
    ) -> dict[str, Any]:
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
            "content_summary_fingerprint": (
                content_summary.fingerprint()
                if content_summary is not None
                else None
            ),
            "content_summary_module_count": (
                len(content_summary.modules)
                if content_summary is not None
                else 0
            ),
            "python_module_summaries": [
                module.canonical_dict()
                for module in modules
            ],
            "python_module_summaries_truncated": (
                content_summary is not None
                and len(modules) < len(content_summary.modules)
            ),
            "relationship_graph_fingerprint": (
                relationship_graph.fingerprint()
                if relationship_graph is not None
                else None
            ),
            "internal_dependency_edge_count": (
                len(relationship_graph.dependency_edges)
                if relationship_graph is not None
                else 0
            ),
            "internal_dependency_edges": [
                edge.canonical_dict()
                for edge in edges
            ],
            "dependency_edges_truncated": (
                relationship_graph is not None
                and len(edges) < len(relationship_graph.dependency_edges)
            ),
            "test_source_link_count": (
                len(relationship_graph.test_source_links)
                if relationship_graph is not None
                else 0
            ),
            "test_source_links": [
                link.canonical_dict()
                for link in links
            ],
            "test_source_links_truncated": (
                relationship_graph is not None
                and len(links) < len(relationship_graph.test_source_links)
            ),
        }

    payload = payload_for(
        selected,
        summary_modules,
        dependency_edges,
        test_source_links,
    )
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    while len(serialized) > max_chars and (
        dependency_edges or test_source_links
    ):
        if len(test_source_links) >= len(dependency_edges) and test_source_links:
            test_source_links.pop()
        elif dependency_edges:
            dependency_edges.pop()
        payload = payload_for(
            selected,
            summary_modules,
            dependency_edges,
            test_source_links,
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    while len(serialized) > max_chars and summary_modules:
        summary_modules.pop()
        payload = payload_for(
            selected,
            summary_modules,
            dependency_edges,
            test_source_links,
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    while len(serialized) > max_chars and selected:
        selected.pop()
        payload = payload_for(
            selected,
            summary_modules,
            dependency_edges,
            test_source_links,
        )
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
