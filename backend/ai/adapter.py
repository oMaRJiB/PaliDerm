"""Omar owns inference. This module has no model/vendor imports."""
from dataclasses import dataclass, field
from typing import Protocol
import math


@dataclass(frozen=True)
class ImageInput:
    """Immutable source reference/hash/MIME for an encrypted image readable through ImageStorage."""
    image_id: int
    storage_reference: str
    sha256: str
    mime_type: str
    quality: str


@dataclass(frozen=True)
class LesionInput:
    """Immutable affected-site grouping of source images."""
    lesion_id: int
    body_site: str
    images: tuple[ImageInput, ...]


@dataclass(frozen=True)
class AnalysisInput:
    """Immutable typed clinical input; sex is canonical and symptom NULL values remain unknown."""
    contract_version: str
    case_id: int
    complaint: str
    duration_days: int | None
    age: int | None
    sex: str | None
    symptoms: dict[str, int | str | None]
    lesions: tuple[LesionInput, ...]
    submitted_at: str


@dataclass(frozen=True)
class Candidate:
    """Adapter-supplied unconfirmed suggestion; confidence may be absent."""
    diagnosis_name: str
    rank: int
    confidence: float | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class AnalysisOutput:
    """Typed adapter output validated before any clinical narrative is persisted."""
    model_name: str
    model_version: str
    prompt_version: str
    triage_level: str
    summary: str
    rationale: str
    limitations: str
    candidates: tuple[Candidate, ...] = ()
    image_quality: dict[int, str] = field(default_factory=dict)

    def validate(self, request: AnalysisInput):
        """Reject malformed output and cross-case image references; never infer clinical thresholds."""
        for value in (self.model_name, self.model_version, self.prompt_version,
                      self.summary, self.rationale, self.limitations):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Missing output text')
        if self.triage_level not in {'red', 'amber', 'green', 'undetermined'}:
            raise ValueError('Invalid triage')
        for rank, item in enumerate(self.candidates, 1):
            if not isinstance(item, Candidate) or type(item.rank) is not int or item.rank != rank:
                raise ValueError('Candidates must have consecutive ordered ranks')
            if not isinstance(item.diagnosis_name, str) or not item.diagnosis_name.strip():
                raise ValueError('Missing candidate name')
            if item.rationale is not None and not isinstance(item.rationale, str):
                raise ValueError('Invalid rationale')
            if item.confidence is not None and (
                type(item.confidence) not in (int, float) or not math.isfinite(item.confidence)
                or not 0 <= item.confidence <= 1
            ):
                raise ValueError('Invalid confidence')
        image_ids = {i.image_id for lesion in request.lesions for i in lesion.images}
        if any(type(key) is not int or key not in image_ids or value not in {'acceptable', 'poor', 'unassessed'}
               for key, value in self.image_quality.items()):
            raise ValueError('Invalid image quality output')


class Adapter(Protocol):
    """Replaceable inference contract owned by Omar; storage encryption does not change its signature."""
    model_name: str
    model_version: str
    prompt_version: str
    def analyze_case(self, input: AnalysisInput) -> AnalysisOutput:
        """Raise AIUnavailable rather than creating an inference attempt or synthetic result."""
        ...


class AIUnavailable(Exception):
    """Signal an intentionally unconfigured inference boundary, independent of clinician review."""
    pass


class UnconfiguredAdapter:
    """Default boundary that never produces fabricated analysis or diagnoses."""
    def analyze_case(self, input: AnalysisInput) -> AnalysisOutput:
        """Raise AIUnavailable rather than creating an inference attempt or synthetic result."""
        raise AIUnavailable('AI integration pending')


# Set create_app({"AI_ADAPTER": your_adapter}) to opt into inference. Default is unconfigured.
adapter: Adapter = UnconfiguredAdapter()
