"""Independent safety seam; no clinical rules have been supplied or invented."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SafetyResult:
    """Independent safety integration state; no clinical policy is configured by default."""
    configured: bool = False
    guidance: str | None = None


class SafetyPolicy(Protocol):
    """Protocol for an externally supplied clinical safety policy, separate from AI."""
    def screen(self, answers: dict) -> SafetyResult:
        """Return unconfigured state without classifying the patient or inventing clinical guidance."""
        ...


class UnconfiguredSafetyPolicy:
    """Default seam that does not invent warning-sign rules."""
    def screen(self, answers: dict) -> SafetyResult:
        """Return unconfigured state without classifying the patient or inventing clinical guidance."""
        return SafetyResult()
