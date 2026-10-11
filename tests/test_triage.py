"""Focused synthetic policy, encrypted persistence and guarded local reset checks."""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from app import create_app
from backend.ai.triage import triage_case, CONDITION_PRIORITIES
from backend.db import get_db
from backend.security import PREFIX
from fixtures import FixtureAdapter
from test_workflow import WorkflowSupport, TEST_ENCRYPTION_KEY


def answers(**changes):
    """Explicit negative answers for every field required by the small policy."""
    result = {'other_symptoms_shortness_of_breath': 0, 'rapidly_worsening': 0,
              'fever': 0, 'discharge': 0}
    result.update(changes)
    return result


def predictions(condition='Dermatitis/Eczema', score=.8):
    """Supply a ranked synthetic score, never real model inference."""
    return [{'condition': condition, 'confidence': score}]


class TriageTests(unittest.TestCase):
    """Verify precedence, unknown handling and explicit negatives without text parsing."""
    def test_emergency_overrides_routine_and_urgent_model(self):
        for condition in ('Dermatitis/Eczema', 'Malignancy/Precancer'):
            result = triage_case(predictions(condition), answers(other_symptoms_shortness_of_breath=1))
            self.assertEqual(result['triage_level'], 'emergency')
            self.assertEqual(result['triage_method'], 'rules_with_model_input')

    def test_urgent_symptoms(self):
        for change in ({'rapidly_worsening': 1}, {'fever': 1, 'discharge': 1}):
            self.assertEqual(triage_case(predictions(), answers(**change))['triage_level'], 'urgent')

    def test_only_top_mapped_prediction_raises_priority(self):
        self.assertEqual(triage_case(predictions('Malignancy/Precancer'), answers())['triage_level'], 'urgent')
        ranked = predictions() + predictions('Malignancy/Precancer', .2)
        self.assertEqual(triage_case(ranked, answers())['triage_level'], 'routine')
        # Uncertainty cannot lower an emergency symptom priority.
        self.assertEqual(triage_case(predictions(score=.1), answers(other_symptoms_shortness_of_breath=1))['triage_level'], 'emergency')

    def test_missing_uncertain_invalid_unknown_outputs(self):
        for output in (None, [], predictions(score=.2), predictions('Other'),
                       predictions('Future label'), predictions(score=float('nan')),
                       predictions(score=True), predictions(score=1.1), [{'condition':'Dermatitis/Eczema'}]):
            self.assertTrue(triage_case(output, answers())['needs_manual_review'])
        self.assertTrue(triage_case(predictions(), {})['needs_manual_review'])
        with self.assertRaises(ValueError):
            triage_case(predictions(), answers(), uncertainty_threshold=2)

    def test_negative_and_free_text_do_not_trigger_rules(self):
        result = triage_case(predictions(), answers(notes='no fever; no shortness of breath'))
        self.assertEqual(result['triage_level'], 'routine')
        self.assertFalse(result['needs_manual_review'])
        result = triage_case(predictions(), 'no fever')
        self.assertEqual(result['triage_level'], 'routine')
        self.assertTrue(result['needs_manual_review'])
        result = triage_case(predictions(), answers(fever='1', other_symptoms_shortness_of_breath='yes'))
        self.assertEqual(result['triage_level'], 'routine')
        self.assertTrue(result['needs_manual_review'])

    def test_mapping_matches_actual_saved_classes(self):
        classes = json.loads((Path(__file__).resolve().parents[1] / 'notebooks/SCIN_custom_classes.json').read_text())['target_classes']
        self.assertEqual(set(classes), set(CONDITION_PRIORITIES))


class TriageStorageTests(WorkflowSupport, unittest.TestCase):
    """Persist output atomically without exposing it or changing clinician control."""
    def test_encrypted_triage_roundtrip_and_manual_review_display(self):
        cid = self.submitted()
        self.login('provider:1')

        class TriageFixture(FixtureAdapter):
            def analyze_case(self, payload):
                """Attach a missing-information result to the existing test-only fixture."""
                return replace(super().analyze_case(payload), triage_level='undetermined',
                               assisted_triage=triage_case(None, {}))

        self.app.config['AI_ADAPTER'] = TriageFixture()
        self.assertEqual(self.post(f'/cases/{cid}/analyze', {'analysis_base':'0'}).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'), 'completed')
        self.assertTrue(self.scalar('SELECT rationale FROM AIAnalysis').startswith(PREFIX))
        envelope = json.loads(self.field('AIAnalysis', 'rationale'))
        self.assertTrue(envelope['triage']['needs_manual_review'])
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('Priority undetermined — manual review needed', page)
        self.assertIn('AI-assisted triage — prototype; clinician review required.', page)
        self.assertEqual(self.scalar('SELECT count(*) FROM ProviderReview'), 0)
        self.login('patient:2')
        self.assertEqual(self.client.get(f'/cases/{cid}').status_code, 403)
        self.login('patient:1')
        self.assertNotIn('AI-assisted triage', self.client.get(f'/cases/{cid}').get_data(as_text=True))


class LocalResetTests(unittest.TestCase):
    """Use temporary synthetic storage only; never reset the working dataset in tests."""
    def test_bare_cli_key_selection_and_full_demo_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'instance').mkdir()
            keyfile = root / 'instance/encryption.key'
            keyfile.write_text(TEST_ENCRYPTION_KEY)
            settings = {'TESTING':True, 'MODEL_PATH':'',
                        'DATABASE':str(root/'demo.sqlite3'), 'UPLOAD_DIR':str(root/'uploads')}
            with patch('app.ROOT', root), patch('backend.demo.ROOT', root), patch.dict(os.environ, {}, clear=True):
                app = create_app(settings)
                old_secret = (root/'instance/session.key').read_text()
                self.assertEqual(Path(app.config['ENCRYPTION_KEY_FILE']), keyfile.resolve())
                orphan = root/'uploads'/('a'*32 + '.png')
                orphan.write_bytes(b'synthetic abandoned file')
                unrelated = root/'uploads'/'keep.txt'
                unrelated.write_text('unrelated')
                for attempt in range(2):
                    result = app.test_cli_runner().invoke(args=['reset-demo','--confirm-demo', '--purge-images','--create-test-accounts'])
                    self.assertEqual(result.exit_code, 0, str(result.exception))
                    with app.app_context():
                        self.assertEqual(get_db().execute('SELECT count(*) FROM Account').fetchone()[0], 5)
                        self.assertEqual(get_db().execute('SELECT count(*) FROM DermCase').fetchone()[0], 1)
                        self.assertEqual(list(get_db().execute('PRAGMA foreign_key_check')), [])
                    self.assertEqual(len(list((root/'uploads').glob('*.png'))), 1)
                self.assertFalse(orphan.exists())
                self.assertTrue(unrelated.exists())
                self.assertEqual(keyfile.read_text(), TEST_ENCRYPTION_KEY)
                self.assertNotEqual((root/'instance/session.key').read_text(), old_secret)
                credentials = root/'instance/test-accounts.txt'
                self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)
                self.assertIn('clinician2 |', credentials.read_text())
                self.assertEqual(app.test_cli_runner().invoke(args=['init-db']).exit_code, 0)


if __name__ == '__main__':
    unittest.main()
