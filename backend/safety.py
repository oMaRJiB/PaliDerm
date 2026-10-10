"""Independent safety seam; no clinical rules have been supplied or invented."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SafetyResult:
    configured: bool = False
    guidance: str | None = None


class SafetyPolicy(Protocol):
    def screen(self, answers: dict) -> SafetyResult: ...


class UnconfiguredSafetyPolicy:
    def screen(self, answers: dict) -> SafetyResult:
        return SafetyResult()
