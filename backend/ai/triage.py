"""Small user-authorized prototype priority policy and legacy review flags.

Neither policy is clinically validated or supplies diagnoses/treatment. Free text
is never interpreted as structured evidence; routine never establishes safety.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Integral
import math
from backend.i18n import translate

# User-authorized illustrative policy, not validated clinical screening. A rule
# matches only when every named structured answer is explicitly positive.
SYMPTOM_RULES = (
    ('emergency', ('other_symptoms_shortness_of_breath',), 'triage_breathing'),
    ('urgent', ('rapidly_worsening',), 'triage_worsening'),
    ('urgent', ('fever', 'discharge'), 'triage_fever_discharge'),
)
CONDITION_PRIORITIES = {
    'Acne/Follicular': 'routine', 'Bacterial Infection': 'routine',
    'Benign Lesion': 'routine', 'Dermatitis/Eczema': 'routine',
    'Fungal Infection': 'routine', 'Hair/Nail Disorder': 'routine',
    'Inflammatory/Autoimmune': 'routine', 'Malignancy/Precancer': 'urgent',
    'Other': 'routine', 'Parasite/Bite': 'routine', 'Pigment Disorder': 'routine',
    'Trauma/Wound': 'routine', 'Vascular/Purpura': 'routine', 'Viral Infection': 'routine',
}
PRIORITY_ORDER = {'routine': 0, 'urgent': 1, 'emergency': 2}
DEFAULT_DEMO_THRESHOLD = 0.5  # Unvalidated uncertainty flag; never a severity cutoff.


def triage_case(predictions, symptoms, *, uncertainty_threshold=DEFAULT_DEMO_THRESHOLD, locale='en'):
    """Return deterministic prototype priority from ranked scores and structured flags.

    Args:
        predictions: Ranked dictionaries with condition/confidence, or None.
            Only the first prediction may raise priority. Scanning every class
            would flag virtually every case because a softmax lists all labels.
        symptoms: Mapping of explicit integer/bool answers, retaining None for
            unanswered values. Free text is never parsed.
        uncertainty_threshold: Configurable, unvalidated top-score threshold
            used only to require review, never to lower symptom-based priority.
        locale: Small catalog locale used for persisted human-readable reasons.

    Returns a JSON-compatible dictionary. Invalid inputs require manual review;
    invalid policy thresholds raise ValueError instead of silently changing rules.
    """
    if type(uncertainty_threshold) not in (int, float) or not math.isfinite(uncertainty_threshold) or not 0 <= uncertainty_threshold <= 1:
        raise ValueError('Invalid demo triage uncertainty threshold')
    symptoms = symptoms if isinstance(symptoms, Mapping) else {}
    reasons = []
    level = 'routine'
    required = {key for _, keys, _ in SYMPTOM_RULES for key in keys}
    missing = any(not (isinstance(symptoms.get(key), Integral) and symptoms[key] in (0, 1)) for key in required)
    manual = missing
    for priority, keys, reason in SYMPTOM_RULES:
        if all(_explicit_yes(symptoms.get(key)) for key in keys):
            if PRIORITY_ORDER[priority] > PRIORITY_ORDER[level]:
                level = priority
            reasons.append(translate(reason, locale))
    if missing:
        reasons.append(translate('triage_missing_symptoms', locale))

    valid = isinstance(predictions, (list, tuple)) and bool(predictions)
    unknown = False
    previous = 1.0
    seen = set()
    if valid:
        for item in predictions:
            if not isinstance(item, Mapping):
                valid = False
                break
            name, score = item.get('condition'), item.get('confidence')
            if not isinstance(name, str) or not name or name in seen:
                valid = False
                break
            seen.add(name)
            unknown = unknown or name not in CONDITION_PRIORITIES
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= previous:
                valid = False
                break
            previous = score
    if not valid:
        manual = True
        reasons.append(translate('triage_invalid_model', locale))
    else:
        top = predictions[0]
        # Confidence controls uncertainty only. Even an uncertain concerning
        # suggestion can raise urgent, but cannot override emergency symptoms.
        if CONDITION_PRIORITIES.get(top['condition']) == 'urgent':
            if PRIORITY_ORDER[level] < PRIORITY_ORDER['urgent']:
                level = 'urgent'
            reasons.append(translate('triage_model_concern', locale, condition=top['condition']))
        if top['confidence'] < uncertainty_threshold or top['condition'] == 'Other':
            manual = True
            reasons.append(translate('triage_uncertain', locale))
        if unknown:
            manual = True
            reasons.append(translate('triage_unmapped', locale))
    if not reasons:
        reasons.append(translate('triage_no_rule', locale))
    return {'triage_level': level, 'triage_reasons': reasons,
            'needs_manual_review': manual, 'triage_method': 'rules_with_model_input'}


def _explicit_yes(value: object) -> bool:
    """Accept True or integer 1; strings, floats, missing values and False fail."""
    return value is True or (isinstance(value, Integral) and not isinstance(value, bool) and value == 1)


def triage_flags(
    predictions: Mapping, symptoms: str | Mapping | None,
    metadata: Mapping | None = None,
) -> list[str]:
    """Return transparent clinician-review flags from the supplied prototype policy.

    Args:
        predictions: Inference result containing top_prediction.condition. Only
            that highest-ranked class is checked, without a confidence cutoff.
        symptoms: Structured flags or uninterpreted free text. Recognized flags
            are rapidly_spreading/spreading, fever and skin_infection_signs.
        metadata: Optional additional structured flags, including
            immunocompromised or immune_status='immunocompromised'.

    Either structured source may explicitly report a flag. Negative, unknown or
    absent values do not become positive. No substring/NLP interpretation of
    symptoms or low-ranked diagnosis scanning occurs. Returned strings request
    clinician review; they never establish an emergency or provide reassurance.
    """
    flags = []
    top = predictions.get("top_prediction")
    condition = top.get("condition") if isinstance(top, Mapping) else None
    condition = condition.strip().casefold() if isinstance(condition, str) else None
    if condition == "melanoma":
        flags.append("Model suspicion of melanoma: clinician review required.")
    elif condition in {"scc", "sccis", "scc/sccis", "squamous cell carcinoma"}:
        flags.append("Model suspicion of squamous cell carcinoma: clinician review required.")

    # Free text is excluded instead of silently guessing clinical flags from it.
    sources = [source for source in (symptoms, metadata) if isinstance(source, Mapping)]
    if any(_explicit_yes(source.get("rapidly_spreading")) for source in sources):
        flags.append("Rapidly spreading rash reported: clinician review required.")
    elif any(_explicit_yes(source.get("spreading")) for source in sources):
        # A report of spread alone does not establish how quickly it occurred.
        flags.append("Spreading rash reported: clinician review required.")
    fever = any(_explicit_yes(source.get("fever")) for source in sources)
    infection = any(_explicit_yes(source.get("skin_infection_signs")) for source in sources)
    if fever and infection:
        flags.append("Fever with skin infection signs reported: clinician review required.")
    immunocompromised = any(_explicit_yes(source.get("immunocompromised")) for source in sources)
    immune_status = any(
        isinstance(source.get("immune_status"), str)
        and source["immune_status"].strip().casefold() == "immunocompromised"
        for source in sources
    )
    if immunocompromised or immune_status:
        flags.append("Immunocompromised status reported: clinician review required.")
    return flags
