from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from ade.control_center import (
    ControlCenterPortfolioSnapshot,
    ControlCenterProjectSummary,
)
from ade.control_center_html import render_control_center
from ade.mission_control import build_mission_control_snapshot


DEFAULT_OUTPUT_DIR = Path("dist/control-center")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _parse_project_spec(value: str) -> tuple[str, Path]:
    label, separator, root = value.partition("=")
    label = label.strip()
    root = root.strip()
    if separator != "=" or not label or not root:
        raise ValueError("project must use non-empty LABEL=ROOT syntax")
    if any(character in label for character in "\r\n\t"):
        raise ValueError("project label must not contain control whitespace")
    return label, Path(root)


def build_artifacts(
    *,
    projects: Sequence[tuple[str, str | Path]],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    if not projects:
        raise ValueError("at least one project is required")

    summaries: list[ControlCenterProjectSummary] = []
    seen_labels: set[str] = set()
    for label, root in projects:
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("project label must be non-empty")
        if normalized_label in seen_labels:
            raise ValueError(f"duplicate project label: {normalized_label}")
        seen_labels.add(normalized_label)

        snapshot = build_mission_control_snapshot(Path(root))
        summary = ControlCenterProjectSummary.from_mission_control(snapshot)
        summaries.append(replace(summary, project_id=normalized_label))

    portfolio = ControlCenterPortfolioSnapshot(projects=tuple(summaries))
    destination = Path(output_dir)
    html_path = destination / "index.html"
    snapshot_path = destination / "snapshot.json"

    snapshot_json = (
        json.dumps(
            portfolio.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    _atomic_write_text(snapshot_path, snapshot_json)
    _atomic_write_text(html_path, render_control_center(portfolio))
    return html_path, snapshot_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the read-only multi-project ADE Control Center artifact.",
    )
    parser.add_argument(
        "--project",
        action="append",
        default=[],
        metavar="LABEL=ROOT",
        help="Project label and checked-out repository root. Repeat for each project.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for index.html and snapshot.json.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        projects = tuple(_parse_project_spec(value) for value in args.project)
        html_path, snapshot_path = build_artifacts(
            projects=projects,
            output_dir=args.output_dir,
        )
    except (ValueError, OSError, TypeError) as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(f"Control Center build failed: {message[:256]}", file=sys.stderr)
        return 1

    print(f"Control Center HTML: {html_path}")
    print(f"Control Center snapshot: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
