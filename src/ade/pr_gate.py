from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GateDecision:
    allowed: bool
    reason: str


FORBIDDEN_EXACT = {
    "GOAL.md",
    "SPEC.md",
    "ACCEPTANCE.md",
    "ROADMAP.md",
    "pyproject.toml",
}
FORBIDDEN_PREFIXES = (
    ".github/",
    ".autodev/",
)


def evaluate_jules_pull_request(
    *,
    repository: str,
    pull_request: dict[str, Any],
    files: list[dict[str, Any]],
) -> GateDecision:
    if pull_request.get("state") != "open":
        return GateDecision(False, "pull request is not open")
    if pull_request.get("draft") is True:
        return GateDecision(False, "draft pull requests are not auto-merged")

    head = pull_request.get("head")
    if not isinstance(head, dict):
        return GateDecision(False, "pull request head is missing")

    head_repo = head.get("repo")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repository:
        return GateDecision(False, "head repository is not the ADE repository")

    head_ref = head.get("ref")
    if not isinstance(head_ref, str) or not head_ref.startswith("feat/"):
        return GateDecision(False, "head branch is not a Jules feature branch")

    body = pull_request.get("body")
    if not isinstance(body, str) or "PR created automatically by Jules for task" not in body:
        return GateDecision(False, "Jules provenance marker is missing")

    if not files:
        return GateDecision(False, "pull request changes no files")

    for changed in files:
        filename = changed.get("filename")
        if not isinstance(filename, str):
            return GateDecision(False, "changed file has no filename")
        if filename in FORBIDDEN_EXACT:
            return GateDecision(False, f"forbidden file changed: {filename}")
        if filename.startswith(FORBIDDEN_PREFIXES):
            return GateDecision(False, f"forbidden path changed: {filename}")

    return GateDecision(True, "Jules provenance and change scope are allowed")
