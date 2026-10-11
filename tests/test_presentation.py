"""HTTP contracts for progressive forms; native-browser checks are separate."""
import unittest
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
        self.assertIn('Case submitted. AI integration pending.', page)
        self.assertIn('data-state="submitted"', page)

    def test_shared_assets_accessible_navigation_and_zero_duration(self):
        cid = self.draft()
        self.details(cid, duration_days='0')
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('name="duration_days" value="0"', page)
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


if __name__ == '__main__':
    unittest.main()
