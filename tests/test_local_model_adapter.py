"""Typed local-model integration using temporary synthetic artifacts, never real ML files."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import has_app_context

from backend.ai.adapter import AIUnavailable, AnalysisInput, ImageInput, LesionInput, UnconfiguredAdapter
from backend.images import ImageStorage
from backend.security import PREFIX
from backend.validation import Problem
from app import create_app
from test_workflow import WorkflowSupport


FEATURE_ITCHING = 'condition_symptoms_itching'
FEATURE_FEVER = 'other_symptoms_fever'


class FormControls(HTMLParser):
    """Inspect native select requirements and visible labels without a browser dependency."""

    def __init__(self, html):
        super().__init__()
        self.selects={}
        self.inputs={}
        self.labels=set()
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attributes=dict(attributes)
        if tag=='select':
            self.selects[attributes.get('name')]=attributes
        elif tag=='input':
            self.inputs[attributes.get('name')]=attributes
        elif tag=='label':
            self.labels.add(attributes.get('for'))


def model_files(directory):
    """Write the smallest valid companion contract; loading dummy model bytes is mocked."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'SCIN_custom_model.keras'
    path.write_bytes(b'SYNTHETIC TEST MODEL; NOT INFERENCE WEIGHTS')
    (directory/'SCIN_custom_metadata_encoder.json').write_text(json.dumps({
        'format_version':1, 'binary_columns':[FEATURE_ITCHING,FEATURE_FEVER],
        'categorical_columns':['sex_at_birth'],
        'categories':[['FEMALE','MALE','OTHER_OR_UNSPECIFIED']],
    }),encoding='utf-8')
    (directory/'SCIN_custom_classes.json').write_text(json.dumps({
        'target_classes':['Eczema','Other'], 'image_size':224,
        'normalization':'RGB float32 /255, letterbox',
    }),encoding='utf-8')
    return path


def model_form(**changes):
    """Provide every model-specific answer explicitly, separate from stored patient intake."""
    values={'model_'+FEATURE_ITCHING:'1','model_'+FEATURE_FEVER:'0',
            'model_sex_at_birth':'OTHER_OR_UNSPECIFIED'}
    values.update(changes)
    return values


def inference_result():
    """Return valid uncalibrated fixture scores with a deliberately unrelated loader version."""
    ranked=[{'condition':'Eczema','confidence':.7},{'condition':'Other','confidence':.3}]
    return {'top_prediction':ranked[0],'differential':ranked,
            'triage_flags':[],'model_version':'ignored-loader-version',
            'warnings':['Synthetic inference fixture only.'],'output_format':'softmax'}


class LocalModelAdapterTests(unittest.TestCase):
    """Exercise supplemental input, lazy binding and immutable artifact identity."""

    def setUp(self):
        from backend.ai.local_adapter import SCINModelAdapter

        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.model_path=model_files(self.directory)
        self.reader=Mock(side_effect=lambda storage_id,sha:storage_id.encode('ascii'))
        self.adapter=SCINModelAdapter(self.model_path,SimpleNamespace(read_original=self.reader))
        images=(ImageInput(11,'a'*32+'.png','1'*64,'image/png','unassessed'),
                ImageInput(12,'b'*32+'.png','2'*64,'image/png','unassessed'))
        self.payload=AnalysisInput('1.0',5,'  شكوى تجريبية  ',2,None,'unknown',
                                   {'itching':None,'pain':0,'bleeding':None,'fever':0,
                                    'discharge':None,'rapidly_worsening':None,'additional_notes':None},
                                   (LesionInput(1,'Arm',images),),'2026-10-11T00:00:00Z')

    def test_metadata_is_explicit_required_validated_and_does_not_change_intake(self):
        original_symptoms=dict(self.payload.symptoms)
        prepared=self.adapter.prepare_input(self.payload,model_form())
        self.assertEqual(prepared.contract_version,'1.1')
        self.assertEqual(prepared.model_metadata,{FEATURE_ITCHING:1,FEATURE_FEVER:0,
                                                  'sex_at_birth':'OTHER_OR_UNSPECIFIED'})
        self.assertIsNone(self.payload.symptoms['itching'])
        self.assertEqual(self.payload.symptoms,original_symptoms)
        self.assertEqual(prepared.symptoms,original_symptoms)
        self.assertEqual(prepared.complaint,self.payload.complaint)
        self.assertEqual(prepared.lesions,self.payload.lesions)
        for field in model_form():
            missing=model_form();missing.pop(field)
            if field == 'model_sex_at_birth':
                self.assertEqual(self.adapter.prepare_input(self.payload,missing).model_metadata['sex_at_birth'],
                                 'OTHER_OR_UNSPECIFIED')
                continue
            with self.subTest(field=field),self.assertRaises(Problem) as error:
                self.adapter.prepare_input(self.payload,missing)
            self.assertEqual(error.exception.key,'ai_inputs_required')
        for invalid in ('2','yes','',None):
            with self.subTest(invalid=invalid),self.assertRaises(Problem):
                self.adapter.prepare_input(self.payload,model_form(**{'model_'+FEATURE_ITCHING:invalid}))
        with self.assertRaises(Problem):
            self.adapter.prepare_input(self.payload,model_form(model_sex_at_birth='not-a-saved-category'))
        with self.assertRaises(Problem) as error:
            self.adapter.prepare_input(self.payload,model_form(**{'model_'+FEATURE_FEVER:'1'}))
        self.assertEqual(error.exception.key,'ai_input_conflict')

    def test_input_fields_prefill_only_explicit_known_symptoms(self):
        fields={field['name'].removeprefix('model_'):field
                for group in self.adapter.input_fields(self.payload) for field in group['fields']}
        self.assertEqual(str(fields[FEATURE_FEVER]['value']),'0')
        self.assertIn(fields[FEATURE_ITCHING]['value'],('',None))

    def test_none_of_listed_flags_cannot_contradict_positive_symptoms(self):
        """Require internally consistent model answers without replacing stored unknowns."""
        local_none='condition_symptoms_no_relevant_experience'
        systemic_none='other_symptoms_no_relevant_symptoms'
        self.adapter.binary_fields+=(local_none,systemic_none)
        # Leave fever unanswered here so the systemic assertion exercises the
        # none-of-listed rule, rather than the separate stored-answer conflict.
        payload=replace(self.payload,symptoms={**self.payload.symptoms,'fever':None})
        base=model_form(**{'model_'+local_none:'0','model_'+systemic_none:'0'})
        self.adapter.prepare_input(payload,base)
        for positive,none_flag in ((FEATURE_ITCHING,local_none),(FEATURE_FEVER,systemic_none)):
            contradictory=dict(base)
            contradictory['model_'+positive]='1'
            contradictory['model_'+none_flag]='1'
            with self.subTest(group=none_flag),self.assertRaises(Problem) as error:
                self.adapter.prepare_input(payload,contradictory)
            self.assertEqual(error.exception.key,'ai_input_conflict')
            consistent=dict(base)
            consistent['model_'+positive]='0'
            consistent['model_'+none_flag]='1'
            self.adapter.prepare_input(payload,consistent)
        self.assertIsNone(self.payload.symptoms['itching'])

    def test_lazy_bound_model_receives_decrypted_multiple_images_and_typed_output(self):
        loaded=Mock()
        loaded.classes=['Eczema','Other']
        loaded.predict_case.return_value=inference_result()
        prepared=self.adapter.prepare_input(self.payload,model_form())
        with patch('backend.ai.local_adapter.load_model',return_value=loaded) as loader, \
                patch('backend.ai.model_interface.predict_case',side_effect=AssertionError('global model must not be used')):
            loader.assert_not_called()
            output=self.adapter.analyze_case(prepared)
            second=self.adapter.analyze_case(prepared)
            self.assertEqual(loader.call_count,1)
        output.validate(prepared)
        self.assertEqual(output.model_name,'SCIN custom CNN')
        self.assertEqual(output.model_version,self.adapter.model_version)
        self.assertNotEqual(output.model_version,'ignored-loader-version')
        self.assertEqual(output.prompt_version,'not-applicable')
        self.assertEqual(output.triage_level,'undetermined')
        self.assertEqual(output.image_quality,{})
        self.assertEqual([item.rank for item in output.candidates],[1,2])
        self.assertEqual([item.diagnosis_name for item in output.candidates],['Eczema','Other'])
        self.assertEqual(output.candidates,second.candidates)
        arguments=loaded.predict_case.call_args.kwargs
        self.assertEqual(arguments['images'],[image.storage_reference.encode('ascii')
                                            for image in self.payload.lesions[0].images])
        self.assertEqual(arguments['symptoms'],self.payload.symptoms)
        self.assertEqual(arguments['metadata'],prepared.model_metadata)
        self.assertEqual(self.reader.call_count,4)

    def test_changed_model_or_encoder_fails_closed_before_inference(self):
        prepared=self.adapter.prepare_input(self.payload,model_form())
        for path in (self.model_path,self.directory/'SCIN_custom_metadata_encoder.json'):
            original=path.read_bytes()
            with self.subTest(path=path.name):
                try:
                    path.write_bytes(original+b'changed')
                    with patch('backend.ai.local_adapter.load_model') as loader,self.assertRaises(AIUnavailable):
                        self.adapter.analyze_case(prepared)
                    loader.assert_not_called()
                finally:
                    path.write_bytes(original)
        self.reader.assert_not_called()

    def test_invalid_scores_and_class_mapping_are_rejected(self):
        """Invalid inference results cannot become persisted typed suggestions."""
        prepared=self.adapter.prepare_input(self.payload,model_form())
        loaded=Mock(classes=['Eczema','Other'])
        with patch('backend.ai.local_adapter.load_model',return_value=loaded):
            for score in (float('nan'),float('inf'),-.1,1.1):
                result=inference_result()
                result['differential'][0]['confidence']=score
                loaded.predict_case.return_value=result
                with self.subTest(score=score),self.assertRaises(ValueError):
                    self.adapter.analyze_case(prepared)
            result=inference_result()
            result['differential'][1]['condition']='Unexpected diagnosis'
            loaded.predict_case.return_value=result
            with self.assertRaises(AIUnavailable):
                self.adapter.analyze_case(prepared)


class LocalModelWorkflowTests(WorkflowSupport,unittest.TestCase):
    """Verify the real encrypted runner boundary with a mocked model execution only."""

    def setUp(self):
        from backend.ai.local_adapter import SCINModelAdapter

        super().setUp()
        path=model_files(self.path/'synthetic-model')
        storage=ImageStorage(self.app.config,self.app.extensions['cipher'])
        self.reader=Mock(wraps=storage.read_original)
        self.adapter=SCINModelAdapter(path,SimpleNamespace(read_original=self.reader))
        self.app.config['AI_ADAPTER']=self.adapter
        self.loaded=Mock()
        self.loaded.classes=['Eczema','Other']
        self.loaded.predict_case.return_value=inference_result()

    def analyze(self,case_id,base='0',**changes):
        form=model_form(**changes);form['analysis_base']=base
        return self.post(f'/cases/{case_id}/analyze',form)

    def test_default_model_path_selects_synthetic_bundle_without_loading_framework(self):
        from backend.ai.local_adapter import SCINModelAdapter

        model_path=model_files(self.path/'notebooks')
        config=dict(self.config)
        config.pop('AI_ADAPTER')
        # Patch ROOT so the default path can never read the user's real weights.
        with patch.dict(os.environ,clear=False),patch('app.ROOT',self.path), \
                patch('backend.ai.local_adapter.load_model') as loader:
            os.environ.pop('MODEL_PATH',None)
            app=create_app(config)
        self.assertEqual(Path(app.config['MODEL_PATH']),model_path)
        self.assertIsInstance(app.config['AI_ADAPTER'],SCINModelAdapter)
        self.assertIsNone(app.config['AI_ADAPTER']._model)
        loader.assert_not_called()

    def test_empty_model_path_explicitly_keeps_unconfigured_adapter(self):
        config=dict(self.config)
        config.pop('AI_ADAPTER')
        config['MODEL_PATH']=''
        with patch('backend.ai.local_adapter.load_model') as loader:
            app=create_app(config)
        self.assertIsInstance(app.config['AI_ADAPTER'],UnconfiguredAdapter)
        self.assertEqual(app.config['AI_ADAPTER'].notice_key,'ai_pending')
        loader.assert_not_called()

    def test_missing_bundle_is_visible_and_does_not_block_manual_review(self):
        case_id=self.submitted()
        self.claim(case_id)
        config=dict(self.config)
        config.pop('AI_ADAPTER')
        config['MODEL_PATH']=str(self.path/'missing-model.keras')
        with patch('backend.ai.local_adapter.load_model') as loader:
            self.app=create_app(config)
            self.client=self.app.test_client()
            self.login('provider:1')
            self.assertEqual(self.app.config['AI_ADAPTER'].notice_key,'ai_model_unavailable')
            page=self.client.get(f'/cases/{case_id}').get_data(as_text=True)
            self.assertIn('Manual review remains available.',page)
            self.assertNotIn('name="model_',page)
            self.assertEqual(self.analyze(case_id).status_code,503)
            self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'),0)
            self.assertEqual(self.post(f'/cases/{case_id}/review',self.review_data()).status_code,302)
        loader.assert_not_called()
        self.assertEqual(self.scalar('SELECT status FROM DermCase'),'reviewed')

    def test_model_checkboxes_are_labeled_and_profile_sex_is_readonly(self):
        case_id=self.submitted()
        with patch('backend.ai.local_adapter.load_model') as loader:
            self.login('provider:1')
            response=self.client.get(f'/cases/{case_id}')
            self.assertEqual(response.status_code,200)
            controls=FormControls(response.get_data(as_text=True))
            for name in model_form():
                with self.subTest(name=name):
                    if name == 'model_sex_at_birth':
                        self.assertNotIn(name,controls.selects)
                        self.assertNotIn(name,controls.inputs)
                    else:
                        self.assertEqual(controls.inputs[name]['type'],'checkbox')
                        self.assertIn(controls.inputs[name]['id'],controls.labels)
            self.login('patient:1')
            response=self.client.get(f'/cases/{case_id}')
            self.assertEqual(response.status_code,200)
            self.assertNotIn('name="model_',response.get_data(as_text=True))
        loader.assert_not_called()

    def test_configured_runner_persists_exact_input_and_encrypted_scores_once(self):
        case_id=self.submitted()
        self.login('provider:1')
        worker_context=[]

        def predict(**arguments):
            worker_context.append(has_app_context())
            self.assertTrue(all(image.startswith(b'\x89PNG') for image in arguments['images']))
            return inference_result()

        self.loaded.predict_case.side_effect=predict
        with patch('backend.ai.local_adapter.load_model',return_value=self.loaded):
            self.assertEqual(self.analyze(case_id).status_code,302)
            self.assertEqual(self.analyze(case_id).status_code,302)
        self.assertEqual(worker_context,[False])
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'),1)
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'),'completed')
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM Diagnosis'),0)
        self.assertTrue(self.scalar('SELECT diagnosis_name FROM AICandidate LIMIT 1').startswith(PREFIX))
        snapshot=json.loads(self.field('AIAnalysis','input_snapshot_json'))
        self.assertEqual(snapshot['contract_version'],'1.1')
        self.assertIsNone(snapshot['symptoms']['itching'])
        self.assertEqual(snapshot['model_metadata'][FEATURE_ITCHING],1)
        self.assertEqual(self.scalar('SELECT image_quality FROM LesionImage LIMIT 1'),'unassessed')

    def test_authorization_and_missing_inputs_precede_model_access(self):
        case_id=self.submitted()
        self.claim(case_id)
        with patch('backend.ai.local_adapter.load_model',return_value=self.loaded) as loader:
            for identity in ('patient:1','worker-demo','provider:2'):
                self.login(identity)
                self.assertEqual(self.analyze(case_id).status_code,403)
            self.login('provider:1')
            self.assertEqual(self.post(f'/cases/{case_id}/analyze',{'analysis_base':'0'}).status_code,400)
        loader.assert_not_called()
        self.reader.assert_not_called()
        self.loaded.predict_case.assert_not_called()
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'),0)

    def test_model_failure_is_sanitized_and_does_not_prevent_manual_review(self):
        case_id=self.submitted()
        self.claim(case_id)
        self.loaded.predict_case.side_effect=ValueError('SENSITIVE MODEL FAILURE DETAIL')
        with patch('backend.ai.local_adapter.load_model',return_value=self.loaded):
            self.assertEqual(self.analyze(case_id).status_code,302)
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'),'failed')
        self.assertEqual(self.scalar('SELECT error_message FROM AIAnalysis'),'adapter_error')
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'),0)
        self.assertNotIn('SENSITIVE MODEL FAILURE DETAIL',
                         self.client.get(f'/cases/{case_id}').get_data(as_text=True))
        self.assertEqual(self.post(f'/cases/{case_id}/review',self.review_data()).status_code,302)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'),'reviewed')

    def test_patient_answers_feed_inference_without_reentering_them(self):
        """Persisted patient choices cross the encrypted snapshot/adapter boundary unchanged."""
        from test_intake import patient_questionnaire

        case_id = self.draft()
        form = patient_questionnaire(intake_action='submit', consent='1')
        from test_workflow import png
        form.add('images', (png(), 'synthetic.png'))
        self.assertEqual(self.post(f'/cases/{case_id}/intake', form).status_code, 302)
        self.claim(case_id)
        with patch('backend.ai.local_adapter.load_model', return_value=self.loaded):
            self.assertEqual(self.post(f'/cases/{case_id}/analyze', {'analysis_base': '0'}).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'), 'completed')
        passed = self.loaded.predict_case.call_args.kwargs['metadata']
        self.assertEqual(passed, {FEATURE_ITCHING: 1, FEATURE_FEVER: 0, 'sex_at_birth': 'OTHER_OR_UNSPECIFIED'})
        snapshot = json.loads(self.field('AIAnalysis', 'input_snapshot_json'))
        self.assertEqual(snapshot['model_metadata'], passed)
        self.assertEqual(snapshot['symptoms']['itching'], 1)
        # A provider cannot rewrite a patient's saved response through supplemental inputs.
        self.assertEqual(self.post(f'/cases/{case_id}/analyze',
                                  {'analysis_base': '1', 'model_'+FEATURE_ITCHING: '0'}).status_code, 400)
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'), 1)

    def test_unknown_patient_checkbox_answers_still_block_only_model_analysis(self):
        from test_intake import patient_questionnaire
        from test_workflow import png

        case_id = self.draft()
        form = patient_questionnaire(intake_action='submit', consent='1')
        form.pop('symptoms_answered')
        form.add('images', (png(), 'synthetic.png'))
        self.assertEqual(self.post(f'/cases/{case_id}/intake', form).status_code, 302)
        self.claim(case_id)
        with patch('backend.ai.local_adapter.load_model') as loader:
            self.assertEqual(self.post(f'/cases/{case_id}/analyze', {'analysis_base': '0'}).status_code, 400)
            loader.assert_not_called()
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'), 0)
        self.assertEqual(self.post(f'/cases/{case_id}/review', self.review_data()).status_code, 302)


if __name__=='__main__':
    unittest.main()
