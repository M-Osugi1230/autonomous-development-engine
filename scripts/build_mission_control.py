from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from ade import build_mission_control_snapshot, render_mission_control


DEFAULT_OUTPUT_DIR = Path("dist/mission-control")


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


def build_artifacts(
    *,
    repo_root: str | Path = ".",
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    root = Path(repo_root)
    destination = Path(output_dir)

    snapshot = build_mission_control_snapshot(root)
    html = render_mission_control(snapshot)
    snapshot_json = (
        json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    html_path = destination / "index.html"
    snapshot_path = destination / "snapshot.json"
    _atomic_write_text(snapshot_path, snapshot_json)
    _atomic_write_text(html_path, html)

    return html_path, snapshot_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the read-only ADE Mission Control artifact.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root containing .autodev/ (default: current directory).",
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
        html_path, snapshot_path = build_artifacts(
            repo_root=args.root,
            output_dir=args.output_dir,
        )
    except (ValueError, OSError, TypeError) as exc:
        message = str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__
        print(f"Mission Control build failed: {message[:256]}", file=sys.stderr)
        return 1

    print(f"Mission Control HTML: {html_path}")
    print(f"Mission Control snapshot: {snapshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
