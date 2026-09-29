from __future__ import annotations

import json

from ade.repository_intelligence import (
    build_repository_snapshot,
    planner_repository_context,
)


def main() -> int:
    paths = [
        ".env.example",
        ".github/workflows/ci.yml",
        "README.md",
        "pyproject.toml",
        "src/thought_pipeline/__init__.py",
        "src/thought_pipeline/models.py",
        "src/thought_pipeline/repository.py",
        "tests/test_models.py",
        "tests/test_repository.py",
    ]
    snapshot = build_repository_snapshot(
        repository="M-Osugi1230/one-minute-thought-experiments",
        base_branch="main",
        source_sha="a" * 40,
        paths=paths,
    )
    reversed_snapshot = build_repository_snapshot(
        repository="M-Osugi1230/one-minute-thought-experiments",
        base_branch="main",
        source_sha="a" * 40,
        paths=reversed(paths),
    )
    assert snapshot.fingerprint() == reversed_snapshot.fingerprint()

    context = planner_repository_context(
        snapshot,
        allowed_path_prefixes=("src/thought_pipeline", "tests"),
        max_files=20,
    )
    known = context.payload["known_files_within_trusted_roots"]
    assert known == [
        "src/thought_pipeline/__init__.py",
        "src/thought_pipeline/models.py",
        "src/thought_pipeline/repository.py",
        "tests/test_models.py",
        "tests/test_repository.py",
    ]
    assert ".github/workflows/ci.yml" not in known
    assert ".env.example" not in known
    assert context.payload["workflow_paths"] == [".github/workflows/ci.yml"]
    assert context.payload["manifest_paths"] == ["pyproject.toml"]
    assert len(context.serialized) <= 12000

    print(json.dumps({
        "ok": True,
        "deterministic_snapshot": True,
        "source_sha_bound": True,
        "writable_root_filtering": True,
        "control_paths_not_writable": True,
        "bounded_planner_context": True,
        "snapshot_fingerprint": snapshot.fingerprint(),
        "context_fingerprint": context.fingerprint,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
