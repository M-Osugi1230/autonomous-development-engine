from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("CheckResult.name must be a non-empty string")


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    results: tuple[CheckResult, ...] = ()

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def complete(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)


def build_report(results: Iterable[CheckResult]) -> AcceptanceReport:
    return AcceptanceReport(results=tuple(results))
