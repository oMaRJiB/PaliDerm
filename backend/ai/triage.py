"""Limited prototype flags from explicitly supplied clinician-review examples.

These rules are not validated emergency screening. They assign no diagnosis,
priority or treatment, and an empty result does not establish that care is safe.
Free text is intentionally not interpreted as structured clinical evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Integral


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
