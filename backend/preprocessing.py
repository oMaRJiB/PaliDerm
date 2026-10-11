"""Deterministic intake encodings only; no model or clinical decisions."""
from datetime import date
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


def symptom_answers(form, previous=None):
    """Normalize browser strings to six int-or-NULL answers; reject malformed flags."""
    if hasattr(form, 'getlist') and len(form.getlist('symptom_ui')) > 1:
        raise Problem('invalid_boolean')
    if form.get('symptom_ui') == 'checkboxes-v1':
        return checkbox_answers(form, SYMPTOM_ORDER, 'symptoms_answered', previous=previous)
    if form.get('symptom_ui') is not None:
        raise Problem('invalid_boolean')
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


def checkbox_answers(form, names, completed_key, *, prefix='', previous=None):
    """Decode select-all answers without treating an untouched box as an explicit No.

    Checked items mean Yes. Only a separate, explicit group confirmation makes
    unchecked items No; otherwise they remain None. Previously recorded No
    answers are preserved when saving an incomplete group. Duplicate/malformed values
    are rejected, including HTTP parameter pollution hidden by ordinary get().
    """
    def checked(key):
        if hasattr(form, 'getlist') and len(form.getlist(key)) > 1:
            raise Problem('invalid_boolean')
        value = form.get(key)
        if value not in (None, '1'):
            raise Problem('invalid_boolean')
        return value == '1'

    complete = checked(completed_key)
    return {name: 1 if checked(prefix + name) else
            (0 if complete or (previous or {}).get(name) == 0 else None) for name in names}


class SCINQuestionnaire:
    """Patient questionnaire contract, independent of model availability and tensor order.

    Stable clinical field names match the supplied SCIN export. The model's saved
    encoder still controls inference ordering. Answers are stored inside the
    existing encrypted Symptom envelope, so older six-answer records need no SQL
    migration and remain readable. No model/runtime import belongs here.
    """
    GROUPS = {
        'textures': tuple('textures_' + name for name in
                          ('raised_or_bumpy', 'flat', 'rough_or_flaky', 'fluid_filled')),
        'body': tuple('body_parts_' + name for name in
                      ('head_or_neck', 'arm', 'palm', 'back_of_hand', 'torso_front', 'torso_back',
                       'genitalia_or_groin', 'buttocks', 'leg', 'foot_top_or_side', 'foot_sole', 'other')),
        'local': tuple('condition_symptoms_' + name for name in
                       ('bothersome_appearance', 'bleeding', 'increasing_size', 'darkening',
                        'itching', 'burning', 'pain', 'no_relevant_experience')),
        'systemic': tuple('other_symptoms_' + name for name in
                          ('fever', 'chills', 'fatigue', 'joint_pain', 'mouth_sores',
                           'shortness_of_breath', 'no_relevant_symptoms')),
    }
    CATEGORIES = {
        'age_group': tuple(f'AGE_{lower}_TO_{lower+9}' for lower in (30, 40, 50, 60, 70)),
        'sex_at_birth': ('FEMALE', 'MALE', 'OTHER_OR_UNSPECIFIED'),
        'fitzpatrick_skin_type': ('FST1', 'FST2', 'FST3', 'FST4', 'FST5', 'FST6', 'NONE_IDENTIFIED', 'UNKNOWN'),
        'related_category': ('ACNE', 'GROWTH_OR_MOLE', 'HAIR_LOSS', 'LOOKS_HEALTHY', 'NAIL_PROBLEM',
                             'OTHER_HAIR_PROBLEM', 'OTHER_ISSUE_DESCRIPTION', 'PIGMENTARY_PROBLEM', 'RASH', 'UNKNOWN'),
        'condition_duration': ('ONE_DAY', 'LESS_THAN_ONE_WEEK', 'ONE_TO_FOUR_WEEKS',
                               'ONE_TO_THREE_MONTHS', 'THREE_TO_TWELVE_MONTHS', 'MORE_THAN_ONE_YEAR',
                               'MORE_THAN_FIVE_YEARS', 'SINCE_CHILDHOOD', 'UNKNOWN'),
    }
    CATEGORIES['age_group'] = ('AGE_18_TO_29',) + CATEGORIES['age_group'] + ('AGE_UNKNOWN',)
    SYMPTOM_FIELDS = {
        'condition_symptoms_itching': 'itching', 'condition_symptoms_pain': 'pain',
        'condition_symptoms_bleeding': 'bleeding', 'other_symptoms_fever': 'fever',
    }

    @staticmethod
    def profile_values(patient, reference_date=None):
        """Derive only the two authorized profile fields; use age at case submission.

        Missing birthdays and ages outside the trained 18–79 bands use the saved
        AGE_UNKNOWN category. The user's existing canonical sex field is reused
        explicitly; it is never inferred from names or other demographic data.
        """
        today = reference_date or date.today()
        age = None
        if patient.get('date_of_birth'):
            born = date.fromisoformat(patient['date_of_birth'])
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return SCINQuestionnaire.demographic_values(age, patient.get('sex'))

    @staticmethod
    def demographic_values(age, sex):
        """Map known profile values to the trained categories, without arbitrary binning."""
        group = 'AGE_UNKNOWN'
        if type(age) is int and 18 <= age <= 79:
            group = 'AGE_18_TO_29' if age < 30 else f'AGE_{age//10*10}_TO_{age//10*10+9}'
        return {'age_group': group,
                'sex_at_birth': {'female': 'FEMALE', 'male': 'MALE'}.get(sex, 'OTHER_OR_UNSPECIFIED')}

    @staticmethod
    def group_for(name):
        """Choose presentation grouping only; never determine model feature order."""
        return ('textures' if name.startswith('textures_') else 'body' if name.startswith('body_parts_')
                else 'systemic' if name.startswith('other_symptoms_') else 'local')

    @staticmethod
    def validate_consistency(values):
        """Reject 'none of the listed' alongside a positive answer, without triage rules."""
        for none_field, prefix in (
                ('condition_symptoms_no_relevant_experience', 'condition_symptoms_'),
                ('other_symptoms_no_relevant_symptoms', 'other_symptoms_')):
            if values.get(none_field) == 1 and any(value == 1 for name, value in values.items()
                                                 if name.startswith(prefix) and name != none_field):
                raise Problem('ai_input_conflict')

    def patient_answers(self, form, patient, symptoms, previous=None, reference_date=None):
        """Validate a draft's extra answers; legacy form posts preserve existing extras.

        Derived fields are server-owned. Ranges do not invent an exact number of
        duration days. Missing extra answers are valid for manual submission;
        inference continues to require complete binary inputs.
        """
        values = dict(previous or {})
        marker = form.get('model_questionnaire_version')
        if hasattr(form, 'getlist') and len(form.getlist('model_questionnaire_version')) > 1:
            raise Problem('invalid_choice')
        if marker not in (None, '1'):
            raise Problem('invalid_choice')
        if marker == '1':
            allowed = {name for names in self.GROUPS.values() for name in names} | set(self.CATEGORIES)
            allowed |= {'questionnaire_version'} | {'group_answered_' + name for name in self.GROUPS}
            if any(key.startswith('model_') and key[6:] not in allowed for key in form):
                raise Problem('invalid_choice')
            if any('model_' + name in form for name in ('age_group', 'sex_at_birth')):
                raise Problem('ai_input_conflict')
            for group, names in self.GROUPS.items():
                names = [name for name in names if name not in self.SYMPTOM_FIELDS]
                values.update(checkbox_answers(form, names, 'model_group_answered_' + group,
                                               prefix='model_', previous=previous))
            for name, options in self.CATEGORIES.items():
                if name in ('age_group', 'sex_at_birth'):
                    continue
                if hasattr(form, 'getlist') and len(form.getlist('model_' + name)) > 1:
                    raise Problem('invalid_choice')
                value = form.get('model_' + name) or None
                if value is not None and value not in options:
                    raise Problem('invalid_choice')
                values[name] = value
        if marker == '1' or values:
            values.update({name: symptoms[key] for name, key in self.SYMPTOM_FIELDS.items()})
            values.update(self.profile_values(patient, reference_date))
            self.validate_consistency(values)
        return values

    def fields(self, values, *, patient=False, binary_fields=None, categories=None):
        """Describe accessible checkbox groups and categorical controls for Jinja."""
        binary_fields = tuple(binary_fields) if binary_fields is not None else tuple(
            name for names in self.GROUPS.values() for name in names)
        groups = {group: [] for group in self.GROUPS}
        for name in binary_fields:
            if patient and name in self.SYMPTOM_FIELDS:
                continue  # Four common symptoms already have their own patient checkboxes.
            groups[self.group_for(name)].append({'name': name, 'label_key': 'scin_' + name,
                                                 'value': values.get(name), 'kind': 'binary'})
        result = [{'label_key': 'scin_group_' + group, 'name': group, 'fields': fields,
                   'complete': all(type(f['value']) is int and f['value'] in (0, 1) for f in fields)}
                  for group, fields in groups.items() if fields]
        category_fields = []
        for name, options in (self.CATEGORIES if categories is None else categories).items():
            category_fields.append({'name': name, 'label_key': 'scin_' + name, 'value': values.get(name),
                                    'kind': 'category', 'readonly': name in ('age_group', 'sex_at_birth'),
                                    'options': [{'value': value, 'label_key': 'scin_' + value} for value in options]})
        if category_fields:
            result.append({'label_key': 'scin_group_demographics', 'name': 'demographics', 'fields': category_fields})
        return result
