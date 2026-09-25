from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    max_repair_attempts_per_task: int = 3
    max_consecutive_failed_cycles: int = 5
    require_human_for_destructive_actions: bool = True
    allow_auto_merge: bool = False

    def validate(self) -> None:
        if self.max_repair_attempts_per_task < 0:
            raise ValueError("max_repair_attempts_per_task must be >= 0")
        if self.max_consecutive_failed_cycles < 1:
            raise ValueError("max_consecutive_failed_cycles must be >= 1")

    def should_escalate_repairs(self, attempts: int) -> bool:
        self.validate()
        return attempts >= self.max_repair_attempts_per_task

    def should_block_project(self, consecutive_failures: int) -> bool:
        self.validate()
        return consecutive_failures >= self.max_consecutive_failed_cycles
