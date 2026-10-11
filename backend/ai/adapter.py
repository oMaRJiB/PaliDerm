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
    # v1.1 adds attempt-specific provider answers; v1.0 callers remain compatible.
    model_metadata: dict[str, int | str] = field(default_factory=dict)


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
    # Optional additive contract; existing adapters and stored attempts stay valid.
    assisted_triage: dict | None = None

    def validate(self, request: AnalysisInput):
        """Reject malformed output and cross-case image references; never infer clinical thresholds."""
        for value in (self.model_name, self.model_version, self.prompt_version,
                      self.summary, self.rationale, self.limitations):
            if not isinstance(value, str) or not value.strip():
                raise ValueError('Missing output text')
        if self.triage_level not in {'red', 'amber', 'green', 'undetermined'}:
            raise ValueError('Invalid triage')
        if self.assisted_triage is not None:
            result = self.assisted_triage
            if (not isinstance(result, dict)
                    or result.get('triage_level') not in {'emergency', 'urgent', 'routine'}
                    or type(result.get('needs_manual_review')) is not bool
                    or result.get('triage_method') != 'rules_with_model_input'
                    or not isinstance(result.get('triage_reasons'), list)
                    or not result['triage_reasons']
                    or any(not isinstance(reason, str) or not reason.strip() for reason in result['triage_reasons'])):
                raise ValueError('Invalid assisted triage')
            priority = {'emergency':'red', 'urgent':'amber', 'routine':'green'}[result['triage_level']]
            if result['triage_level'] == 'routine' and result['needs_manual_review']:
                priority = 'undetermined'
            if self.triage_level != priority:
                raise ValueError('Inconsistent assisted triage priority')
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
    """Disabled/unavailable boundary that never fabricates analysis or diagnoses."""
    def __init__(self, notice_key='ai_pending'):
        """Keep absent inference distinct from an explicitly selected broken bundle."""
        self.notice_key = notice_key

    def analyze_case(self, input: AnalysisInput) -> AnalysisOutput:
        """Raise AIUnavailable rather than creating an inference attempt or synthetic result."""
        raise AIUnavailable('AI integration pending')


# Standalone contract default; Flask selects Omar's saved bundle via MODEL_PATH,
# or accepts an explicit create_app({"AI_ADAPTER": your_adapter}) override.
adapter: Adapter = UnconfiguredAdapter()
