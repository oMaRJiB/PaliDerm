"""Connect saved SCIN inference to authorized, encrypted application cases.

The model interface owns tensors and preprocessing. This bridge owns recorded
patient/supplemental metadata and typed output; it never trains or changes a model.
"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from threading import Lock

from backend.ai.adapter import AIUnavailable, AnalysisOutput, Candidate
from backend.ai.model_interface import load_model
from backend.ai.triage import triage_case
from backend.i18n import translate
from backend.validation import Problem
from backend.preprocessing import SCINQuestionnaire, checkbox_answers


class SCINModelAdapter:
    """Load one immutable model bundle lazily and require its actual saved inputs.

    Args:
        model_path: Trusted administrator-selected local model file.
        image_reader: ImageStorage holding the already-verified application cipher.
        locale: Locale used for the persisted, clinician-visible model notices.

    Missing or incompatible companion JSON raises AIUnavailable at configuration.
    Model execution errors propagate to the runner's sanitized failure handling.
    """
    model_name = 'SCIN custom CNN'
    prompt_version = 'not-applicable'
    notice_key = 'ai_configured'
    _symptom_fields = {
        'condition_symptoms_itching': 'itching',
        'condition_symptoms_pain': 'pain',
        'condition_symptoms_bleeding': 'bleeding',
        'other_symptoms_fever': 'fever',
    }
    _policy_version = b'scin-patient-inputs-v2;profile-demographics;explicit-checkbox-groups;mean-probabilities'

    def __init__(self, model_path, image_reader, locale='en', *, triage_threshold=0.5):
        """Bind saved artifacts and an explicitly unvalidated prototype triage threshold."""
        self.path = Path(model_path).resolve()
        self.image_reader = image_reader
        self.locale = locale
        # Validate policy configuration before any case is analyzed.
        triage_case(None, {}, uncertainty_threshold=triage_threshold)
        self.triage_threshold = triage_threshold
        self._model = None
        self._load_lock = Lock()
        if self.path.suffix.lower() == '.keras':
            prefix = self.path.stem.removesuffix('_model')
            encoder = self.path.with_name(f'{prefix}_metadata_encoder.json')
            classes = self.path.with_name(f'{prefix}_classes.json')
        else:
            encoder = self.path.parent / 'metadata_encoder.json'
            classes = self.path.parent / 'class_mapping.json'
            self.model_name = 'SCIN saved model'
        self._files = [self.path, encoder, classes]
        # Include optional contracts the inference loader may read; a restart is
        # required after changing weights, class order, encoder or preprocessing.
        self._optional_files = [Path(str(self.path) + '.json'),
                                self.path.parent / 'inference_config.json',
                                self.path.parent / 'manifest.json']
        if self.path.parent / 'class_mapping.json' != classes:
            self._optional_files.append(self.path.parent / 'class_mapping.json')
        self._files += [path for path in self._optional_files if path.is_file()]
        try:
            schema = json.loads(encoder.read_text(encoding='utf-8'))
            self.classes = tuple(json.loads(classes.read_text(encoding='utf-8'))['target_classes'])
            self.binary_fields = tuple(schema['binary_columns'])
            self.categorical_fields = tuple(schema['categorical_columns'])
            categories = schema['categories']
            if (schema.get('format_version') != 1
                    or len(categories) != len(self.categorical_fields)
                    or len(self.classes) < 2 or len(set(self.classes)) != len(self.classes)
                    or any(not isinstance(name, str) or not name.strip() for name in self.classes)):
                raise ValueError()
            names = self.binary_fields + self.categorical_fields
            if (not names or len(set(names)) != len(names)
                    or any(not isinstance(name, str) or not name.isidentifier() for name in names)):
                raise ValueError()
            self.categories = dict(zip(self.categorical_fields, categories))
            if any(not isinstance(values, list) or not values
                   or len(set(values)) != len(values)
                   or any(not isinstance(value, str) or not value for value in values)
                   for values in self.categories.values()):
                raise ValueError()
            self._fingerprint = self._bundle_fingerprint()
        except (OSError, ValueError, TypeError, KeyError):
            raise AIUnavailable('Saved SCIN model or required encoder/class mapping is unavailable.') from None
        self.model_version = 'sha256:' + self._fingerprint

    def _bundle_fingerprint(self):
        """Bind output provenance to weights, preprocessing and this input policy."""
        digest = hashlib.sha256(self._policy_version)
        digest.update(f';prototype-triage-v1;threshold={self.triage_threshold}'.encode('ascii'))
        for path in self._files:
            digest.update(path.name.encode('utf-8') + b'\0')
            with path.open('rb') as stream:
                digest.update(hashlib.file_digest(stream, 'sha256').digest())
        return digest.hexdigest()

    def _check_bundle(self):
        """Reject hot replacements instead of using new files under an old version."""
        try:
            expected_optional = {path for path in self._files if path in self._optional_files}
            if ({path for path in self._optional_files if path.is_file()} != expected_optional
                    or self._bundle_fingerprint() != self._fingerprint):
                raise ValueError()
        except (OSError, ValueError):
            raise AIUnavailable('Model bundle changed; restart the application to select it consistently.') from None

    def input_fields(self, payload=None, *, metadata=None):
        """Prefill patient answers; profile-derived age/sex are displayed read-only."""
        symptoms = getattr(payload, 'symptoms', payload) or {}
        values = dict(metadata if metadata is not None else getattr(payload, 'model_metadata', {}))
        for name in self.binary_fields:
            known = symptoms.get(self._symptom_fields.get(name))
            if type(known) is int and known in (0, 1):
                values[name] = known
        if metadata is None:
            values.update(SCINQuestionnaire.demographic_values(getattr(payload, 'age', None), getattr(payload, 'sex', None)))
        groups = SCINQuestionnaire().fields(values, binary_fields=self.binary_fields, categories=self.categories)
        for group in groups:
            for field in group['fields']:
                if values.get(field['name']) is not None:
                    if field['kind'] == 'binary':
                        field['locked'] = True
                    else:
                        field['readonly'] = True
        return groups

    def prepare_input(self, payload, form):
        """Validate provider answers before persisting the exact encrypted snapshot.

        Returns a new AnalysisInput; submitted symptom NULLs and all original
        clinical data remain untouched. Missing/invalid answers raise Problem.
        """
        form = {} if form is None else form
        names = self.binary_fields + self.categorical_fields
        allowed = set(names) | {'questionnaire_version'} | {'group_answered_' + group for group in SCINQuestionnaire.GROUPS}
        if any(key.startswith('model_') and key[6:] not in allowed for key in form):
            raise Problem('ai_inputs_required')
        marker = form.get('model_questionnaire_version')
        if hasattr(form, 'getlist') and len(form.getlist('model_questionnaire_version')) > 1:
            raise Problem('ai_inputs_required')
        if marker not in (None, '1'):
            raise Problem('ai_inputs_required')
        checkbox_values = {}
        if marker == '1':
            for group in SCINQuestionnaire.GROUPS:
                fields = [name for name in self.binary_fields if SCINQuestionnaire.group_for(name) == group]
                checkbox_values.update(checkbox_answers(form, fields, 'model_group_answered_' + group, prefix='model_'))
        derived = SCINQuestionnaire.demographic_values(payload.age, payload.sex)
        # Patient snapshots already carry age at submission and verified profile
        # sex; direct typed callers derive the same categories from their context.
        derived.update({name: payload.model_metadata[name] for name in derived if name in payload.model_metadata})
        metadata = {}
        for name in names:
            key = 'model_' + name
            if hasattr(form, 'getlist') and len(form.getlist(key)) > 1:
                raise Problem('ai_inputs_required')
            saved = payload.model_metadata.get(name)
            if name in derived:
                value = derived[name]
                if key in form and form.get(key) != value:
                    raise Problem('ai_input_conflict')
            elif name in self.binary_fields and marker == '1':
                # Disabled, already-recorded answers are intentionally absent
                # from browser FormData; their authenticated source wins.
                value = saved if key not in form and saved is not None else checkbox_values.get(name)
                if value is None:
                    value = saved
            else:
                value = form.get(key, saved)
            if name in self.binary_fields:
                if not (type(value) is int and value in (0, 1)) and value not in ('0', '1'):
                    raise Problem('ai_inputs_required')
                value = int(value)
                original = payload.symptoms.get(self._symptom_fields.get(name))
                if original is not None and original != value:
                    raise Problem('ai_input_conflict')
            elif value not in self.categories[name]:
                raise Problem('ai_inputs_required')
            if saved is not None and saved != value:
                raise Problem('ai_input_conflict')
            metadata[name] = value
        # These saved checkbox categories literally mean "none of the listed";
        # rejecting contradictory answers is input consistency, not clinical triage.
        SCINQuestionnaire.validate_consistency(metadata)
        return replace(payload, contract_version='1.1', model_metadata=metadata)

    def analyze_case(self, input):
        """Authenticate image bytes and return real model scores as typed suggestions.

        No Flask context or database access is needed in the inference thread.
        Mandatory metadata comes from explicit answers and authorized profile
        derivations, never imputed absent symptoms.
        """
        if set(input.model_metadata) != set(self.binary_fields + self.categorical_fields):
            raise AIUnavailable('Required model inputs are missing.')
        with self._load_lock:
            self._check_bundle()
            if self._model is None:
                loaded = load_model(self.path)
                self._check_bundle()
                if tuple(loaded.classes or ()) != self.classes:
                    raise AIUnavailable('Loaded model class order differs from its configured mapping.')
                self._model = loaded
        images = [self.image_reader.read_original(image.storage_reference, image.sha256)
                  for lesion in input.lesions for image in lesion.images]
        if not images:
            raise AIUnavailable('No authorized source images are available.')
        # Retain this bound model, rather than a process-global active model that
        # another caller could replace after the runner recorded our model version.
        result = self._model.predict_case(images=images, symptoms=input.symptoms,
                                          metadata=input.model_metadata)
        differential = result['differential']
        if (len(differential) != len(self.classes)
                or {item['condition'] for item in differential} != set(self.classes)):
            raise AIUnavailable('Prediction classes differ from the saved mapping.')
        candidates = tuple(Candidate(item['condition'], rank, float(item['confidence']))
                           for rank, item in enumerate(differential, 1))
        warnings = result.get('warnings', [])
        limitations = translate('ai_local_limitations', self.locale)
        if warnings:
            limitations += '\n' + '\n'.join(warnings)
        # Structured patient answers only. Original six symptom fields remain
        # authoritative over supplemental model metadata for shared names.
        triage = triage_case(differential, {**input.model_metadata, **input.symptoms},
                             uncertainty_threshold=self.triage_threshold, locale=self.locale)
        priority = {'emergency':'red', 'urgent':'amber', 'routine':'green'}[triage['triage_level']]
        if triage['triage_level'] == 'routine' and triage['needs_manual_review']:
            priority = 'undetermined'
        output = AnalysisOutput(
            model_name=self.model_name, model_version=self.model_version,
            prompt_version=self.prompt_version, triage_level=priority,
            summary=translate('ai_local_summary', self.locale, count=len(candidates)),
            rationale=translate('ai_local_rationale', self.locale),
            limitations=limitations, candidates=candidates, assisted_triage=triage,
        )
        output.validate(input)
        return output
