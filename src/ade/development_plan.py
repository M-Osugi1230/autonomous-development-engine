from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any


@dataclass(frozen=True, slots=True)
class PlannedTask:
    task_id: str
    title: str
    prompt: str
    depends_on: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    acceptance: tuple[str, ...]

    def validate(self) -> None:
        if not self.task_id.strip() or not self.title.strip() or not self.prompt.strip():
            raise ValueError("planned task identity, title, and prompt are required")
        if not self.allowed_paths or not self.acceptance:
            raise ValueError("planned task requires allowed_paths and acceptance")
        for path in self.allowed_paths:
            p=PurePosixPath(path)
            if path.startswith("/") or ".." in p.parts or path in {".github", ".autodev"} or path.startswith(".github/") or path.startswith(".autodev/"):
                raise ValueError(f"unsafe planned path: {path}")


@dataclass(frozen=True, slots=True)
class DevelopmentPlan:
    goal: str
    tasks: tuple[PlannedTask, ...]
    human_boundaries: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.goal.strip() or not self.tasks or len(self.tasks) > 12:
            raise ValueError("plan requires a goal and 1..12 tasks")
        ids={t.task_id for t in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("duplicate task id")
        for task in self.tasks:
            task.validate()
            if any(dep not in ids or dep == task.task_id for dep in task.depends_on):
                raise ValueError("invalid dependency")
        visiting:set[str]=set(); done:set[str]=set()
        deps={t.task_id:set(t.depends_on) for t in self.tasks}
        def visit(node:str)->None:
            if node in visiting: raise ValueError("cyclic plan")
            if node in done: return
            visiting.add(node)
            for dep in deps[node]: visit(dep)
            visiting.remove(node); done.add(node)
        for node in ids: visit(node)

    def canonical_dict(self) -> dict[str, Any]:
        return {"schema_version":1,"goal":" ".join(self.goal.split()),"tasks":[{"task_id":t.task_id,"title":" ".join(t.title.split()),"prompt":" ".join(t.prompt.split()),"depends_on":list(t.depends_on),"allowed_paths":list(t.allowed_paths),"acceptance":list(t.acceptance)} for t in self.tasks],"human_boundaries":list(self.human_boundaries)}

    def fingerprint(self) -> str:
        self.validate()
        raw=json.dumps(self.canonical_dict(),sort_keys=True,separators=(",",":"))
        return hashlib.sha256(raw.encode()).hexdigest()
