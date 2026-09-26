from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .task_graph import TaskGraph


DEFAULT_TASK_GRAPH_PATH = Path(".autodev/task-graph.json")


class TaskGraphStore:
    """Atomically persist the repository-backed task graph."""

    def __init__(self, path: str | Path = DEFAULT_TASK_GRAPH_PATH) -> None:
        self.path = Path(path)

    def load(self) -> TaskGraph:
        if not self.path.exists():
            raise FileNotFoundError(f"task graph file not found: {self.path}")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"task graph contains invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("task graph file must contain a JSON object")
        return TaskGraph.from_dict(payload)

    def save(self, graph: TaskGraph) -> None:
        if not isinstance(graph, TaskGraph):
            raise TypeError("graph must be a TaskGraph")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    graph.to_dict(),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
