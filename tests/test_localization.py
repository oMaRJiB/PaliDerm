"""English/Arabic presentation, locale security and unchanged encrypted clinical text."""
import string
import unittest
from dataclasses import replace

from flask import g, render_template_string

from app import create_app
from backend.ai.adapter import Candidate
from backend.i18n import (CATALOG, brief_triage_reason, display_ai_narrative,
                          display_condition, translate)
from fixtures import FixtureAdapter
from test_workflow import ARABIC, PASSWORD, WorkflowSupport


class LocalizationTests(WorkflowSupport, unittest.TestCase):
    """Exercise locale display through real routes without changing stored English values."""

    def switch(self, locale, next_path='/'):
        """Submit the ordinary, CSRF-protected language form."""
        return self.post('/locale', {'locale': locale, 'next': next_path})

    def signup_data(self, **updates):
        """Return synthetic bilingual profile data with Latin technical identifiers."""
        values = {'username': 'bilingual-user', 'password': PASSWORD,
                  'password_confirm': PASSWORD, 'first_name': '  عمر  ',
                  'last_name': 'Jibreen', 'date_of_birth': '2000-02-29',
                  'sex': 'female', 'email': 'patient@example.test',
                  'phone': '+1-202-555-0101'}
        return {**values, **updates}

    def assert_arabic_page(self, path, *labels):
        """Check the document direction and translated labels on an authorized route."""
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        page = response.get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl">', page)
        self.assertIn('<title>PaliDerm</title>', page)
        self.assertNotIn('prototype', page.lower())
        for label in labels:
            self.assertIn(translate(label, 'ar'), page, (path, label))
        return page

    def test_catalog_is_complete_and_preserves_format_placeholders(self):
        """A missing Arabic label must not silently fall back to an English form."""
        self.assertEqual(set(CATALOG['en']), set(CATALOG['ar']))
        formatter = string.Formatter()
        for key, english in CATALOG['en'].items():
            arabic = CATALOG['ar'][key]
            self.assertIsInstance(arabic, str, key)
            self.assertTrue(arabic.strip(), key)
            english_fields = {field for _, field, _, _ in formatter.parse(english)
                              if field is not None}
            arabic_fields = {field for _, field, _, _ in formatter.parse(arabic)
                             if field is not None}
            self.assertEqual(english_fields, arabic_fields, key)
        self.assertEqual(translate('app_title', 'en'), 'PaliDerm')
        self.assertEqual(translate('app_title', 'ar'), 'PaliDerm')

    def test_locale_requires_csrf_and_rejects_invalid_values_and_external_redirects(self):
        """Changing presentation may neither bypass CSRF nor redirect to another site."""
        with self.client.session_transaction() as session:
            account, csrf = session['account_id'], session['csrf']
        self.assertEqual(self.client.post('/locale', data={'locale': 'ar'}).status_code, 400)
        self.assertEqual(self.client.get('/locale').status_code, 405)
        for values in ({'locale': 'fr', 'next': '/'},
                       {'locale': 'ar', 'next': 'https://example.test/'},
                       {'locale': 'ar', 'next': '//example.test/'},
                       {'locale': 'ar', 'next': '/\\example.test/'}):
            self.assertEqual(self.post('/locale', values).status_code, 400, values)
        response = self.switch('ar', '/my-cases')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/my-cases')
        with self.client.session_transaction() as session:
            self.assertEqual(session['locale'], 'ar')
            self.assertEqual(session['account_id'], account)
            self.assertEqual(session['csrf'], csrf)

    def test_locale_survives_signed_cookie_restart_and_switches_back_to_english(self):
        """The same authenticated browser keeps its chosen language after an app restart."""
        arabic_default = create_app({**self.config, 'APP_LOCALE': 'ar'})
        self.assertIn('<html lang="ar" dir="rtl">',
                      arabic_default.test_client().get('/login').get_data(as_text=True))
        self.assertEqual(self.switch('ar').status_code, 302)
        restarted = create_app(self.config)
        browser = restarted.test_client()
        browser.set_cookie('session', self.client.get_cookie('session').value)
        page = browser.get('/my-cases', follow_redirects=True).get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl">', page)
        self.assertIn(translate('my_cases', 'ar'), page)
        with browser.session_transaction() as session:
            token = session['csrf']
            self.assertIn('account_id', session)
        response = browser.post('/locale', data={'locale': 'en', 'next': '/', 'csrf': token})
        self.assertEqual(response.status_code, 302)
        english = browser.get('/').get_data(as_text=True)
        self.assertIn('<html lang="en" dir="ltr">', english)
        self.assertIn('Synthetic demonstration only.', english)
        self.assertIn('Not clinically validated.', english)
        self.assertNotIn('prototype', english.lower())

    def test_arabic_login_signup_intake_case_queue_and_review_pages(self):
        """Patient and clinician forms share Arabic labels while preserving role restrictions."""
        self.post('/logout')
        self.switch('ar')
        self.assert_arabic_page('/login', 'login', 'username', 'password', 'prototype', 'emergency')
        register = self.assert_arabic_page('/patients/new', 'register', 'first_name', 'email', 'phone')
        self.assertIn('id="technical-field-help"', register)
        self.assertIn(translate('english_only_help', 'ar'), register)
        for field in ('username', 'email', 'phone'):
            self.assertRegex(register, rf'<input\b(?=[^>]*\bname="{field}")(?=[^>]*\bdir="ltr")[^>]*>')
        self.login('patient:1')
        with self.client.session_transaction() as session:
            self.assertEqual(session['locale'], 'ar')
        cid = self.draft()
        self.assert_arabic_page(f'/cases/{cid}', 'chief_complaint', 'save_draft', 'patient_model_questions')
        self.assertEqual(self.details(cid).status_code, 302)
        self.assertEqual(self.upload(cid).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 302)
        self.assert_arabic_page(f'/cases/{cid}', 'submitted', 'symptoms', 'released')
        self.post('/logout')
        with self.client.session_transaction() as session:
            self.assertEqual(session['locale'], 'ar')
        self.login('provider:1')
        with self.client.session_transaction() as session:
            self.assertEqual(session['locale'], 'ar')
        self.assert_arabic_page('/queue', 'queue', 'status')
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'claim'}).status_code, 302)
        self.assert_arabic_page(f'/cases/{cid}', 'review', 'patient_message', 'clinical_notes')
        self.assertEqual(self.scalar('SELECT status FROM DermCase WHERE case_id=?', (cid,)), 'in_review')

    def test_latin_technical_fields_are_validated_without_restricting_names(self):
        """HTML hints are backed by validation and invalid signup leaves no orphan patient."""
        self.post('/logout')
        self.switch('ar')
        before = self.scalar('SELECT count(*) FROM Patient')
        for updates in ({'username': 'مستخدم'}, {'email': 'مريض@example.test'},
                        {'phone': '+١-٢٠٢-٥٥٥-٠١٠١'}, {'phone': '٠١٢٣٤٥٦٧٨٩'}):
            result = self.post('/patients/new', self.signup_data(**updates))
            self.assertEqual(result.status_code, 400, updates)
            self.assertIn('<html lang="ar" dir="rtl">', result.get_data(as_text=True))
            self.assertEqual(self.scalar('SELECT count(*) FROM Patient'), before)
        result = self.post('/patients/new', self.signup_data())
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'), before + 1)
        self.assertEqual(self.scalar("SELECT role FROM Account WHERE username='bilingual-user'"), 'patient')
        profile = self.client.get('/patients/3').get_data(as_text=True)
        self.assertIn('  عمر  ', profile)
        self.assertIn('Jibreen', profile)
        self.assertIn('+1-202-555-0101', profile)
        self.assertIn('patient@example.test', profile)

    def test_arabic_notes_survive_encryption_restart_and_english_stored_enums(self):
        """Presentation translation never rewrites entered text or persisted workflow values."""
        self.switch('ar')
        cid = self.submitted()
        self.claim(cid)
        self.switch('ar')
        clinician_note = '  ملاحظة الطبيب — Patient wrote: no fever  '
        self.assertEqual(self.post(f'/cases/{cid}/review',
                                   self.review_data(clinical_notes=clinician_note)).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM DermCase WHERE case_id=?', (cid,)), 'reviewed')
        self.assertEqual(self.scalar('SELECT decision FROM ProviderReview'), 'confirmed')
        self.assertEqual(self.scalar('SELECT triage_level FROM ProviderReview'), 'undetermined')
        self.assertEqual(self.field('DermCase', 'chief_complaint'), ARABIC)
        self.assertEqual(self.field('Symptom', 'additional_notes'), ARABIC)
        self.assertEqual(self.field('ProviderReview', 'clinical_notes'), clinician_note)
        self.assertNotIn(clinician_note, self.scalar('SELECT clinical_notes FROM ProviderReview'))
        restarted = create_app(self.config)
        browser = restarted.test_client()
        browser.set_cookie('session', self.client.get_cookie('session').value)
        page = browser.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl">', page)
        self.assertIn(ARABIC, page)
        self.assertIn(clinician_note, page)
        self.assertIn('  عمر تجريبي  ', page)

    def test_known_model_labels_and_reasons_translate_but_free_text_stays_exact(self):
        """Only known generated phrases are translated; clinician/user content is preserved."""
        self.assertNotEqual(display_condition('Dermatitis/Eczema', 'ar'), 'Dermatitis/Eczema')
        self.assertEqual(display_condition('Dermatitis/Eczema', 'en'),
                         translate('condition_Dermatitis/Eczema', 'en'))
        self.assertEqual(display_condition(ARABIC, 'ar'), ARABIC)
        self.assertEqual(display_ai_narrative(ARABIC, 'ar'), ARABIC)
        self.assertEqual(brief_triage_reason(ARABIC, 'ar'), ARABIC)
        legacy = 'Shortness of breath was reported (illustrative emergency rule).'
        self.assertEqual(brief_triage_reason(legacy, 'ar'), translate('triage_breathing', 'ar'))
        current = translate('triage_worsening', 'en')
        self.assertEqual(brief_triage_reason(current, 'ar'), translate('triage_worsening', 'ar'))
        concern = translate('triage_model_concern', 'en', condition='Malignancy/Precancer')
        self.assertEqual(brief_triage_reason(concern, 'ar'),
                         translate('triage_model_concern', 'ar',
                                   condition=display_condition('Malignancy/Precancer', 'ar')))
        narrative = translate('ai_local_summary', 'en', count=14)
        self.assertEqual(display_ai_narrative(narrative, 'ar'),
                         translate('ai_local_summary', 'ar', count=14))
        legacy_limitations = ('This prototype can be wrong. It does not check photo quality '
                              'or interpret written notes. Extra answers entered by a clinician '
                              'are saved with this analysis only.')
        for locale in ('en', 'ar'):
            self.assertEqual(display_ai_narrative(legacy_limitations, locale),
                             translate('ai_local_limitations', locale))
        with self.app.test_request_context():
            g.locale = 'ar'
            rendered = render_template_string('{{ value|condition_label }}', value='Dermatitis/Eczema')
            self.assertEqual(rendered, display_condition('Dermatitis/Eczema', 'ar'))

    def test_arabic_ai_report_translates_saved_english_output_without_changing_labels(self):
        """Previously saved model labels remain compatible with inference and translate on display."""
        cid = self.submitted()
        self.login('provider:1')

        class BilingualFixture(FixtureAdapter):
            """Use synthetic adapter output to test display without loading an ML framework."""

            def analyze_case(self, payload):
                return replace(super().analyze_case(payload),
                    candidates=(Candidate('Dermatitis/Eczema', 1, .42),),
                    summary=translate('ai_local_summary', 'en', count=14),
                    rationale=translate('ai_local_rationale', 'en'),
                    limitations=translate('ai_local_limitations', 'en'),
                    assisted_triage={'triage_level': 'routine', 'needs_manual_review': True,
                        'triage_method': 'rules_with_model_input',
                        'triage_reasons': [translate('triage_missing_symptoms', 'en')]})

        self.app.config['AI_ADAPTER'] = BilingualFixture()
        self.assertEqual(self.post(f'/cases/{cid}/analyze', {'analysis_base': '0'}).status_code, 302)
        self.switch('ar')
        page = self.assert_arabic_page(f'/cases/{cid}', 'triage_manual', 'assisted_triage_notice',
                                      'triage_missing_symptoms', 'ai_disclaimer')
        self.assertIn(display_condition('Dermatitis/Eczema', 'ar'), page)
        self.assertNotIn('Dermatitis/Eczema', page)
        self.assertIn(translate('ai_local_summary', 'ar', count=14), page)
        self.assertEqual(self.field('AICandidate', 'diagnosis_name'), 'Dermatitis/Eczema')
        self.assertNotIn('Dermatitis/Eczema', self.scalar('SELECT diagnosis_name FROM AICandidate'))
        self.assertEqual(self.scalar('SELECT confidence FROM AICandidate'), .42)


if __name__ == '__main__':
    unittest.main()
