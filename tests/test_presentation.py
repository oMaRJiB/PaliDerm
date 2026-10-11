"""HTTP contracts for progressive forms; native-browser checks are separate."""
import unittest
from dataclasses import replace
from flask import render_template_string
from backend.ai.adapter import Candidate
from fixtures import FixtureAdapter
from test_workflow import WorkflowSupport


class PresentationTests(WorkflowSupport, unittest.TestCase):
    def enhanced(self, path, data):
        with self.client.session_transaction() as session:
            csrf = session['csrf']
        return self.client.post(path, data={**data, 'csrf': csrf},
                                headers={'X-Form-Response': 'json'})

    def test_enhanced_submit_preserves_notice_and_errors_allow_retry(self):
        cid = self.draft()
        failed = self.enhanced(f'/cases/{cid}/submit', {'consent': '1'})
        self.assertEqual(failed.status_code, 400)
        self.assertIn('role="alert"', failed.get_data(as_text=True))
        self.assertEqual(self.scalar('SELECT status FROM DermCase WHERE case_id=?', (cid,)), 'draft')
        self.details(cid)
        self.upload(cid)
        response = self.enhanced(f'/cases/{cid}/submit', {'consent': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'redirect': f'/cases/{cid}'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        page = self.client.get(response.json['redirect']).get_data(as_text=True)
        self.assertIn('Case submitted for clinician review.', page)
        self.assertIn('data-state="submitted"', page)

    def test_shared_assets_accessible_navigation_and_zero_duration(self):
        cid = self.draft()
        self.details(cid, duration_days='0')
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('Previously recorded duration in days: <bdi dir="ltr">0</bdi>', page)
        self.assertIn('name="model_condition_duration"', page)
        self.assertIn('href="/static/app.css"', page)
        self.assertIn('src="/static/forms.js"', page)
        self.assertIn('href="#main"', page)
        self.assertIn('data-network-error=', page)
        self.assertIn('data-selected-preview=', page)
        self.assertIn('dir="auto"', page)
        profile = self.client.get('/patients/1').get_data(as_text=True)
        self.assertIn('href="/my-cases" aria-current="page"', profile)
        for asset in ('/static/app.css', '/static/forms.js'):
            with self.client.get(asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_enhanced_forms_do_not_bypass_csrf_or_ownership(self):
        cid = self.draft()
        self.assertEqual(self.client.post(f'/cases/{cid}/submit', data={'consent': '1'},
                         headers={'X-Form-Response': 'json'}).status_code, 400)
        self.login('patient:2')
        denied = self.enhanced(f'/cases/{cid}/draft', {'chief_complaint': 'Denied'})
        self.assertEqual(denied.status_code, 403)
        self.assertIn('role="alert"', denied.get_data(as_text=True))

    def test_enhanced_assignment_redirect_and_other_provider_denial(self):
        """Named action controls submit to the transition route with existing security."""
        cid = self.submitted()
        self.login('provider:1')
        response = self.enhanced(f'/cases/{cid}/transition', {'action':'claim'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {'redirect':f'/cases/{cid}'})
        self.assertEqual(self.scalar('SELECT status FROM DermCase WHERE case_id=?', (cid,)), 'in_review')
        self.assertEqual(self.scalar('SELECT provider_id FROM DermCase WHERE case_id=?', (cid,)), 1)
        self.assertEqual(self.client.get(response.json['redirect']).status_code, 200)
        self.login('provider:2')
        self.assertEqual(self.enhanced(f'/cases/{cid}/transition', {'action':'claim'}).status_code, 403)

    def test_ai_report_percentages_short_legacy_reasons_and_expandable_details(self):
        """Stored scores/history remain exact while clinician presentation becomes simpler."""
        cid = self.submitted()
        self.login('provider:1')

        class ReadableFixture(FixtureAdapter):
            def analyze_case(self, payload):
                """Attach synthetic scores and a legacy explanation for display regression."""
                return replace(super().analyze_case(payload), candidates=(
                    Candidate('Dermatitis/Eczema',1,.42), Candidate('Fungal Infection',2,.18),
                    Candidate('Benign Lesion',3,.003), Candidate('Other',4,None)),
                    assisted_triage={'triage_level':'routine','needs_manual_review':True,
                        'triage_method':'rules_with_model_input',
                        'triage_reasons':['Required structured symptom answers are missing or invalid; manual review is needed.']})

        self.app.config['AI_ADAPTER'] = ReadableFixture()
        self.assertEqual(self.enhanced(f'/cases/{cid}/analyze', {'analysis_base':'0'}).status_code, 200)
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('AI match score: <bdi dir="ltr">42%</bdi>', page)
        self.assertIn('18%</bdi>', page)
        self.assertIn('Less than 1%</bdi>', page)
        self.assertIn('Score unavailable</bdi>', page)
        self.assertNotIn('0.42', page)
        self.assertNotIn('0.003', page)
        self.assertIn('Some symptom answers are missing or unclear.', page)
        self.assertNotIn('Required structured symptom answers are missing or invalid;', page)
        self.assertIn('Priority undetermined — manual review needed', page)
        self.assertIn('not the chance of having the condition', page)
        self.assertIn('<details><summary>Other suggestions</summary><ol class="ai-suggestions" start="4">', page)
        self.assertIn('<details><summary>How this result was produced and its limits</summary>', page)
        self.assertEqual(self.scalar('SELECT confidence FROM AICandidate WHERE rank=1'), .42)
        self.assertEqual(self.scalar('SELECT confidence FROM AICandidate WHERE rank=3'), .003)
        self.assertEqual(self.scalar('SELECT count(*) FROM AICandidate'), 4)

    def test_score_display_bounds(self):
        """Do not display tiny positive scores as zero or almost-one scores as certainty."""
        with self.app.test_request_context():
            for value, expected in ((None,'Score unavailable'), (0,'0%'), (.0002,'Less than 1%'),
                                    (.01,'1%'), (.42,'42%'), (.99,'99%'), (.9999,'Over 99%'), (1,'100%')):
                self.assertEqual(render_template_string('{{ value|ai_score }}', value=value), expected)

    def test_timestamp_markup_utc_fallback_and_date_only_fields(self):
        """Localize only display timestamps; preserve UTC data and calendar dates."""
        cid = self.submitted()
        before = self.scalar('SELECT submitted_at FROM DermCase WHERE case_id=?', (cid,))
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn(f'<time datetime="{before}" data-local-time dir="auto">{before} UTC</time>', page)
        self.assertIn('data-time-local="Times use your device’s timezone."', page)
        self.assertNotIn('<dt>Initial submission (UTC)</dt>', page)
        profile = self.client.get('/patients/1').get_data(as_text=True)
        self.assertIn('data-local-time', profile)
        self.login('provider:1')
        queue = self.client.get('/queue').get_data(as_text=True)
        self.assertIn(f'datetime="{before}"', queue)
        self.assertEqual(self.scalar('SELECT submitted_at FROM DermCase WHERE case_id=?', (cid,)), before)
        with self.app.test_request_context():
            rendered = render_template_string("{% from 'macros.html' import timestamp with context %}{{ timestamp(none) }}", t=lambda key:'Unknown')
            self.assertEqual(rendered, 'Unknown')


if __name__ == '__main__':
    unittest.main()
