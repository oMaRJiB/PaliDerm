"""Deterministic intake encodings only; no model or clinical decisions."""
from backend.validation import Problem

GENDERS = ('female', 'male', 'unknown')
SYMPTOM_ORDER = ('itching', 'pain', 'bleeding', 'discharge', 'fever', 'rapidly_worsening')


def normalize_gender(value, *, legacy=False):
    """Return a canonical gender; unknown legacy text is archived by the migration.

    New unrecognized input raises Problem. Missing values represent unknown;
    legacy F/M are accepted only during migration, never inferred from a name.
    """
    if value is not None and not isinstance(value, str):
        if legacy:
            return 'unknown'
        raise Problem('invalid_gender')
    normalized = value.strip().casefold() if isinstance(value, str) else ''
    aliases = {'': 'unknown', 'unknown/prefer not to say': 'unknown', 'prefer not to say': 'unknown'}
    if legacy:
        aliases.update({'f': 'female', 'm': 'male'})
    normalized = aliases.get(normalized, normalized)
    if normalized in GENDERS:
        return normalized
    if legacy:
        return 'unknown'
    raise Problem('invalid_gender')


def gender_one_hot(value):
    """Return [female, male, unknown] with exactly one active value."""
    gender = normalize_gender(value)
    return [int(gender == option) for option in GENDERS]


def symptom_answers(form):
    """Normalize browser strings to six int-or-NULL answers; reject malformed flags."""
    answers = {}
    for key in SYMPTOM_ORDER:
        value = form.get(key, '')
        if value not in ('', '0', '1'):
            raise Problem('invalid_boolean')
        answers[key] = None if value == '' else int(value)
    return answers


def symptom_vector(answers):
    """Return values in SYMPTOM_ORDER, retaining None instead of inventing 'No'."""
    values = [answers.get(key) for key in SYMPTOM_ORDER]
    if any(value is not None and (type(value) is not int or value not in (0, 1)) for value in values):
        raise Problem('invalid_boolean')
    return values
