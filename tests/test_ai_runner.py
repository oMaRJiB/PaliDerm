"""Storage/lifecycle contract tests using developer fixtures; no model inference."""
import json
import time
import unittest
from dataclasses import replace
from test_workflow import WorkflowSupport
from fixtures import FixtureAdapter
from backend.ai.runner import recover_interrupted
from backend.db import get_db
from backend.security import cipher
from backend import services as svc


class AIRunnerTests(WorkflowSupport, unittest.TestCase):
    def test_configured_success_failure_retry_preserves_history(self):
        cid = self.submitted()
        self.login('provider:1')
        self.app.config['AI_ADAPTER'] = FixtureAdapter()
        response = self.post(f'/cases/{cid}/analyze', {'analysis_base':'0'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'), 'completed')
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'), 1)
        self.assertEqual(self.scalar('SELECT image_quality FROM LesionImage LIMIT 1'), 'poor')
        self.assertEqual(self.scalar('SELECT count(*) FROM Diagnosis'), 0)
        snapshot = json.loads(self.field('AIAnalysis', 'input_snapshot_json'))
        self.assertIsNone(snapshot['symptoms']['itching'])
        self.assertEqual(snapshot['lesions'][0]['images'][0]['quality'], 'unassessed')
        self.post(f'/cases/{cid}/analyze', {'analysis_base':'0'})
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'), 1)
        class Failing(FixtureAdapter):
            def analyze_case(self,input):
                raise RuntimeError('SENSITIVE ADAPTER DETAIL')
        self.app.config['AI_ADAPTER'] = Failing()
        self.post(f'/cases/{cid}/analyze', {'analysis_base':'1'})
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis ORDER BY analysis_id DESC LIMIT 1'),'failed')
        self.assertEqual(self.scalar('SELECT error_message FROM AIAnalysis ORDER BY analysis_id DESC LIMIT 1'),'adapter_error')
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('Latest AI result',page)
        self.assertIn('SIMULATED AI — not model inference',page)
        self.assertNotIn('SENSITIVE ADAPTER DETAIL',page)
        self.assertEqual(self.scalar("SELECT count(*) FROM AIAnalysis WHERE status='completed'"),1)
        self.app.config['AI_ADAPTER'] = FixtureAdapter()
        self.post(f'/cases/{cid}/analyze', {'analysis_base':'2'})
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'),3)
        self.assertEqual(self.post(f'/cases/{cid}/transition',{'action':'claim'}).status_code,302)
        self.assertEqual(self.post(f'/cases/{cid}/review',self.review_data()).status_code,302)

    def test_invalid_adapter_output_rolls_back_result_candidates_quality(self):
        cid = self.submitted()
        self.login('provider:1')
        class Invalid(FixtureAdapter):
            def analyze_case(self,input):
                return replace(super().analyze_case(input),triage_level='invalid')
        self.app.config['AI_ADAPTER'] = Invalid()
        self.post(f'/cases/{cid}/analyze', {'analysis_base':'0'})
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'),'failed')
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'),0)
        self.assertEqual(self.scalar('SELECT image_quality FROM LesionImage LIMIT 1'),'unassessed')

    def test_timeout_interrupted_recovery_and_manual_review(self):
        cid = self.submitted()
        self.login('provider:1')
        class Slow(FixtureAdapter):
            def analyze_case(self,input):
                time.sleep(.05)
                return super().analyze_case(input)
        self.app.config['AI_ADAPTER'] = Slow()
        self.app.config['AI_TIMEOUT_SECONDS'] = .001
        self.post(f'/cases/{cid}/analyze', {'analysis_base':'0'})
        self.assertEqual(self.scalar('SELECT status FROM AIAnalysis'),'failed')
        self.assertEqual(self.scalar('SELECT error_message FROM AIAnalysis'),'timeout')
        time.sleep(.06)  # allow test worker to exit; late results must not be committed
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'),0)
        with self.app.app_context(), svc.transaction() as db:
            db.execute("INSERT INTO AIAnalysis(case_id,model_name,model_version,prompt_version,input_snapshot_json,status) VALUES(?,'fixture','1','not-applicable',?,'running')",(cid,json.dumps({'encrypted':cipher().encrypt('{}','AIAnalysis.input_snapshot_json')})))
        recover_interrupted(self.config['DATABASE'])
        self.assertEqual(self.scalar('SELECT error_message FROM AIAnalysis ORDER BY analysis_id DESC LIMIT 1'),'interrupted')
        self.assertEqual(self.post(f'/cases/{cid}/transition',{'action':'claim'}).status_code,302)
        self.assertEqual(self.post(f'/cases/{cid}/review',self.review_data()).status_code,302)
