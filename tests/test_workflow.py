"""Synthetic end-to-end workflow, integrity and rollback regression coverage."""
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from PIL import Image
from werkzeug.datastructures import MultiDict
from cryptography.fernet import Fernet
from app import create_app
from backend.security import reveal, cipher, encrypt_text
from backend.images import ImageStorage
from backend.auth import AuthService
from backend.db import connect, get_db
from backend import services as svc
from backend.ai.adapter import (AnalysisInput, AnalysisOutput, Candidate, AIUnavailable, UnconfiguredAdapter)

TEST_ENCRYPTION_KEY = Fernet.generate_key().decode('ascii')

PASSWORD = 'Synthetic-test-password-123!'

ARABIC = '  شكوى جلدية — حكة في اليد؛ ملاحظات تجريبية  '


def png():
    stream = io.BytesIO()
    Image.new('RGB', (32, 24), 'gray').save(stream, format='PNG')
    stream.seek(0)
    return stream


class WorkflowSupport:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = {'TESTING': True, 'SECRET_KEY': 'test-only', 'ENCRYPTION_KEY': TEST_ENCRYPTION_KEY, 'ENCRYPTION_KEY_FILE': None,
                       'DATABASE': str(self.path/'test.sqlite3'), 'UPLOAD_DIR': str(self.path/'uploads')}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        with self.app.app_context():
            self.p1 = svc.create_patient({'first_name': '  عمر تجريبي  ', 'last_name': 'Demo', 'date_of_birth': '2000-02-29', 'phone': '555-0101'})
            self.p2 = svc.create_patient({'first_name': 'Synthetic', 'last_name': 'Other'})
            with svc.transaction() as db:
                db.execute("INSERT INTO Provider(name) VALUES('Synthetic Clinician')")
                db.execute("INSERT INTO Provider(name) VALUES('Other Clinician')")
        with self.app.app_context():
            auth = AuthService()
            for ident in (1, 2):
                auth.provision(f'patient{ident}', PASSWORD, 'patient', patient_id=ident)
                auth.provision(f'provider{ident}', PASSWORD, 'provider', provider_id=ident)
            auth.provision('worker', PASSWORD, 'worker')
        self.login('patient:1')

    def login(self, identity):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            csrf = session['csrf']
        username = 'worker' if identity == 'worker-demo' else identity.replace(':', '')
        return self.client.post('/login', data={'username': username, 'password': PASSWORD, 'csrf': csrf})

    def post(self, path, data=None):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            csrf = session['csrf']
        values = MultiDict(data or {})
        values['csrf'] = csrf
        return self.client.post(path, data=values)

    def draft(self):
        response = self.post('/patients/1/cases', {'chief_complaint': ARABIC, 'duration_days': '2'})
        self.assertEqual(response.status_code, 302)
        return int(response.location.rsplit('/', 1)[1])

    def details(self, case_id, **updates):
        data = {'chief_complaint': ARABIC, 'duration_days': '2', 'itching': '', 'pain': '0', 'body_sites': ['8', '7'], 'additional_notes': ARABIC}
        data.update(updates)
        return self.post(f'/cases/{case_id}/draft', data)

    def upload(self, case_id, count=2):
        with self.app.app_context():
            lesion = get_db().execute('SELECT lesion_id FROM Lesion WHERE case_id=? ORDER BY lesion_id', (case_id,)).fetchone()[0]
        data = MultiDict([('lesion_id', str(lesion))] + [('images', (png(), f'demo{i}.jpeg')) for i in range(count)])
        return self.post(f'/cases/{case_id}/images', data)

    def submitted(self):
        cid = self.draft()
        self.assertEqual(self.details(cid).status_code, 302)
        self.assertEqual(self.upload(cid).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 302)
        return cid

    def claim(self, cid):
        self.login('provider:1')
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'claim'}).status_code, 302)

    def review_data(self, **updates):
        data = {'decision': 'confirmed', 'triage_level': 'undetermined', 'patient_message': ARABIC,
                'clinical_notes': 'PRIVATE CLINICIAN NOTE', 'diagnosis_0': 'Synthetic clinician diagnosis',
                'certainty_0': 'provisional', 'instructions_0': 'Synthetic instructions only',
                'medication_0': 'Demo documentation only', 'dosage_0': 'Demo', 'primary': '0',
                'followup_date': '2026-12-01', 'review_base': '0'}
        data.update(updates)
        return data

    def field(self, table, key):
        """Read a decoded clinical field explicitly; raw scalar() still tests actual SQL."""
        with self.app.app_context():
            return reveal(table, get_db().execute(f'SELECT * FROM {table}').fetchone())[key]

    def scalar(self, sql, params=()):
        with self.app.app_context():
            return get_db().execute(sql, params).fetchone()[0]



class WorkflowTests(WorkflowSupport, unittest.TestCase):
    def test_complete_flow_arabic_and_restart(self):
        cid = self.submitted()
        self.claim(cid)
        response = self.post(f'/cases/{cid}/review', self.review_data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scalar('SELECT count(*) FROM TreatmentPlan'), 1)
        self.assertEqual(self.scalar('SELECT analysis_id FROM ProviderReview'), None)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'reviewed')
        self.login('patient:1')
        page = self.client.get(f'/cases/{cid}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(ARABIC, page.get_data(as_text=True))
        self.assertNotIn('PRIVATE CLINICIAN NOTE', page.get_data(as_text=True))
        self.assertIn('Provisional', page.get_data(as_text=True))
        self.assertIn('Synthetic instructions only', page.get_data(as_text=True))
        # Fresh app/DB connections emulate application restart; reuse signed local demo cookie.
        restarted = create_app(self.config)
        browser = restarted.test_client()
        cookie = self.client.get_cookie('session')
        browser.set_cookie('session', cookie.value)
        page = browser.get(f'/cases/{cid}')
        self.assertEqual(page.status_code, 200)
        self.assertIn(ARABIC, page.get_data(as_text=True))
        self.assertIn('  عمر تجريبي  ', page.get_data(as_text=True))
        with browser.get('/images/1') as image_response:
            self.assertEqual(image_response.status_code, 200)
        self.assertEqual(self.field('DermCase', 'chief_complaint'), ARABIC)
        self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 2)
        self.assertEqual(self.scalar('PRAGMA user_version'), 4)

    def test_submission_consent_and_nulls_idempotent_freeze(self):
        cid = self.draft()
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 400)
        self.details(cid)
        self.assertIsNone(self.field('Symptom', 'itching'))
        self.assertEqual(self.field('Symptom', 'pain'), 0)
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 400)
        self.upload(cid)
        self.assertEqual(self.post(f'/cases/{cid}/submit').status_code, 400)
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': 'yes'}).status_code, 400)
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 302)
        stamp = self.scalar('SELECT submitted_at FROM DermCase')
        self.assertEqual(self.post(f'/cases/{cid}/submit', {'consent': '1'}).status_code, 302)
        self.assertEqual(self.scalar('SELECT submitted_at FROM DermCase'), stamp)
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'), 0)
        self.assertEqual(self.details(cid).status_code, 409)
        self.assertEqual(self.upload(cid).status_code, 409)

    def test_validation_dates_durations_and_booleans(self):
        self.post('/logout')
        credentials = {'username': 'newpatient', 'password': PASSWORD, 'password_confirm': PASSWORD}
        for values in ({'first_name':'x','last_name':'y','date_of_birth':'2025-02-30'},
                       {'first_name':'x','last_name':'y','date_of_birth':'2999-01-01'},
                       {'first_name':'   ','last_name':'y'}):
            self.assertEqual(self.post('/patients/new', {**credentials, **values}).status_code, 400)
        self.login('patient:1')
        for value in ('-1', '1.5', 'nan', '99999999999999999999999999', ' 1'):
            self.assertEqual(self.post('/patients/1/cases', {'chief_complaint': 'Demo', 'duration_days': value}).status_code, 400)
        cid = self.draft()
        self.assertEqual(self.details(cid, pain='false').status_code, 400)
        self.assertEqual(self.details(cid, body_sites=['999']).status_code, 400)
        self.assertEqual(self.scalar('SELECT count(*) FROM Symptom'), 0)
        self.assertEqual(self.details(cid, duration_days='').status_code, 302)
        self.assertIsNone(self.field('DermCase', 'duration_days'))
        self.details(cid, additional_notes='  نص عربي  ')
        self.assertEqual(self.scalar('SELECT count(*) FROM Symptom'), 1)
        self.assertEqual(self.field('Symptom', 'additional_notes'), '  نص عربي  ')

    def test_authorization_private_images_assignment_and_worker(self):
        cid = self.submitted()
        self.login('patient:2')
        for url in (f'/cases/{cid}', '/images/1', '/patients/1', '/queue'):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post('/patients/1/cases', {'chief_complaint': 'Not mine'}).status_code, 403)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 403)
        self.login('worker-demo')
        self.assertEqual(self.client.get(f'/cases/{cid}').status_code, 403)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'claim'}).status_code, 403)
        self.claim(cid)
        self.login('provider:2')
        self.assertEqual(self.client.get(f'/cases/{cid}').status_code, 403)
        self.assertEqual(self.client.get('/images/1').status_code, 403)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 403)
        self.assertNotIn(ARABIC, self.client.get('/queue').get_data(as_text=True))
        self.post('/logout')
        self.assertEqual(self.client.get('/images/1').status_code, 403)
        self.assertEqual(self.client.get('/static/uploads/1.png').status_code, 404)

    def test_provider_cannot_read_patient_draft(self):
        cid = self.draft()
        self.login('provider:1')
        self.assertEqual(self.client.get(f'/cases/{cid}').status_code, 403)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'claim'}).status_code, 403)

    def test_csrf_and_local_gate(self):
        self.assertEqual(self.client.post('/patients/new', data={'first_name': 'x','last_name':'y'}).status_code, 400)
        self.assertEqual(self.client.get('/', environ_overrides={'REMOTE_ADDR': '192.0.2.1'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host': 'malicious.example'}).status_code, 403)
        self.assertEqual(self.post('/login', {'identity': 'patient:999'}).status_code, 401)

    def test_upload_validation_hash_metadata_and_rollback(self):
        cid = self.draft()
        self.details(cid)
        with self.app.app_context():
            lesion = get_db().execute('SELECT lesion_id FROM Lesion ORDER BY lesion_id').fetchone()[0]
        data = MultiDict([('lesion_id', str(lesion)), ('images', (png(),'valid.png')),
                          ('images',(io.BytesIO(b'not an image'), 'invalid.png'))])
        self.assertEqual(self.post(f'/cases/{cid}/images', data).status_code, 400)
        self.assertEqual(list((self.path/'uploads').iterdir()), [])
        self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 0)
        self.assertEqual(self.upload(cid, 1).status_code, 302)
        with self.app.app_context():
            row = get_db().execute('SELECT * FROM LesionImage').fetchone()
            stored = ImageStorage(self.app.config).read_original(row['image_uri'], row['content_sha256'])
            self.assertNotEqual(stored, (self.path/'uploads'/row['image_uri']).read_bytes())
            self.assertEqual(hashlib.sha256(stored).hexdigest(), row['content_sha256'])
            self.assertEqual(row['mime_type'], 'image/png')
            with Image.open(io.BytesIO(stored)) as im:
                self.assertEqual(len(im.getexif()), 0)
        self.assertEqual(self.details(cid, body_sites=[]).status_code, 400)
        self.app.config['MAX_IMAGE_COUNT'] = 1
        self.assertEqual(self.upload(cid, 1).status_code, 400)
        # Legacy app pixel caps no longer reject ordinary photos.
        self.app.config['MAX_IMAGE_PIXELS'] = 10
        self.app.config['MAX_IMAGE_COUNT'] = 12
        self.assertEqual(self.upload(cid, 1).status_code, 302)

    def test_review_validation_primary_referral_date(self):
        cid = self.submitted()
        self.claim(cid)
        invalid = [self.review_data(diagnosis_0=''), self.review_data(primary='1'),
                   self.review_data(followup_date='2026-02-30'), self.review_data(patient_message=' '),
                   self.review_data(decision='referred'),
                   self.review_data(referral_required='1',referral_reason=' '),
                   self.review_data(diagnosis_0='',decision='inconclusive')]
        for data in invalid:
            self.assertEqual(self.post(f'/cases/{cid}/review', data).status_code, 400)
        self.assertEqual(self.scalar('SELECT count(*) FROM ProviderReview'), 0)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'in_review')
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data(diagnosis_1='Second synthetic diagnosis')).status_code, 302)
        self.assertEqual(self.scalar('SELECT sum(is_primary) FROM Diagnosis'), 1)
        self.assertEqual(self.scalar('SELECT count(*) FROM Diagnosis'), 2)

    def test_transactional_review_rollback_on_database_failure(self):
        cid = self.submitted()
        self.claim(cid)
        with self.app.app_context(), svc.transaction() as db:
            db.execute("CREATE TRIGGER simulate_storage_failure BEFORE INSERT ON TreatmentPlan BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 503)
        for table in ('ProviderReview','Diagnosis','TreatmentPlan'):
            self.assertEqual(self.scalar(f'SELECT count(*) FROM {table}'), 0)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'in_review')

    def test_legal_transitions_review_history_and_retries(self):
        cid = self.submitted()
        self.login('provider:1')
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 403)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'close'}).status_code, 409)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'claim'}).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 409)
        self.assertEqual(self.scalar('SELECT count(*) FROM ProviderReview'), 1)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'revise'}).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 409)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data(review_base='1', patient_message='Revised synthetic result')).status_code, 302)
        self.assertEqual(self.scalar('SELECT count(*) FROM ProviderReview'), 2)
        self.login('patient:1')
        self.assertIn('Revised synthetic result', self.client.get(f'/cases/{cid}').get_data(as_text=True))
        self.login('provider:1')
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'close'}).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action': 'revise'}).status_code, 409)
        self.login('patient:1')
        self.assertEqual(self.details(cid).status_code, 409)

    def test_needs_information_without_destructive_resubmission(self):
        cid = self.submitted()
        self.claim(cid)
        data = self.review_data(decision='needs_information',diagnosis_0='', instructions_0='', medication_0='',dosage_0='', patient_message='Please clarify the fictional duration externally.')
        self.assertEqual(self.post(f'/cases/{cid}/review', data).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'needs_information')
        self.login('patient:1')
        self.assertIn('Please clarify', self.client.get(f'/cases/{cid}').get_data(as_text=True))
        self.assertEqual(self.details(cid).status_code, 409)
        self.assertEqual(self.field('DermCase', 'chief_complaint'), ARABIC)
        self.assertEqual(self.scalar('SELECT count(*) FROM Diagnosis'), 0)

    def test_referral_without_diagnosis(self):
        cid = self.submitted()
        self.claim(cid)
        data = self.review_data(decision='referred',referral_required='1',referral_destination='Synthetic emergency department',
                                referral_reason='Synthetic explicit urgent escalation documentation', triage_level='red',
                                diagnosis_0='',instructions_0='',medication_0='',dosage_0='')
        self.assertEqual(self.post(f'/cases/{cid}/review', data).status_code, 302)
        self.assertEqual(self.scalar('SELECT count(*) FROM Diagnosis'), 0)
        self.assertEqual(self.scalar('SELECT referral_required FROM ProviderReview'), 1)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'reviewed')
        self.login('patient:1')
        self.assertIn('Synthetic emergency department', self.client.get(f'/cases/{cid}').get_data(as_text=True))

    def test_cross_case_foreign_keys_and_unique_primary(self):
        cid = self.submitted()
        self.claim(cid)
        self.post(f'/cases/{cid}/review', self.review_data())
        with self.app.app_context():
            db = get_db()
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            with self.assertRaises(sqlite3.IntegrityError), svc.transaction() as db:
                db.execute('INSERT INTO Diagnosis(case_id,review_id,diagnosis_name) VALUES(999,1,?)', (encrypt_text('Diagnosis','diagnosis_name','Invalid cross case'),))
            with self.assertRaises(sqlite3.IntegrityError), svc.transaction() as db:
                db.execute('INSERT INTO Diagnosis(case_id,review_id,diagnosis_name) VALUES(1,1,?)', (encrypt_text('Diagnosis','diagnosis_name','Second primary'),))
            with svc.transaction() as db:
                other = db.execute('INSERT INTO DermCase(patient_id,chief_complaint,encrypted_duration) VALUES(2,?,?)', (encrypt_text('DermCase','chief_complaint','Other demo'), cipher().encrypt(None,'DermCase.duration_days'))).lastrowid
                aid = db.execute("INSERT INTO AIAnalysis(case_id,model_name,model_version,prompt_version,input_snapshot_json) VALUES(?,'test','1','not-applicable',?)", (other, json.dumps({'encrypted':cipher().encrypt('{}','AIAnalysis.input_snapshot_json')}))).lastrowid
            with self.assertRaises(sqlite3.IntegrityError), svc.transaction() as db:
                db.execute('UPDATE ProviderReview SET analysis_id=? WHERE review_id=1', (aid,))

    def test_ai_unavailable_does_not_create_attempt_or_block_manual_review(self):
        cid = self.submitted()
        self.login('provider:1')
        self.assertEqual(self.post(f'/cases/{cid}/analyze').status_code, 503)
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'), 0)
        self.assertIn('AI integration pending', self.client.get(f'/cases/{cid}').get_data(as_text=True))
        with self.app.app_context():
            request = svc.CaseWorkflow({'role':'provider','id':1}).build_analysis_input(cid)
            snapshot = json.loads(json.dumps(asdict(request), ensure_ascii=False))
            self.assertIsNone(snapshot['symptoms']['itching'])
            self.assertEqual(snapshot['symptoms']['pain'], 0)
            self.assertEqual(snapshot['complaint'], ARABIC)
            self.assertNotIn('first_name', snapshot)
            self.assertEqual(snapshot['lesions'][0]['images'][0]['sha256'], self.scalar('SELECT content_sha256 FROM LesionImage ORDER BY image_id LIMIT 1'))
            with self.assertRaises(AIUnavailable):
                UnconfiguredAdapter().analyze_case(request)
        self.assertEqual(self.post(f'/cases/{cid}/transition', {'action':'claim'}).status_code, 302)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 302)

    def test_invalid_ai_output_contract(self):
        cid = self.submitted()
        with self.app.app_context():
            request = svc.CaseWorkflow({'role':'provider','id':1}).build_analysis_input(cid)
            output = AnalysisOutput('SIMULATED AI — not model inference', 'fixture-1', 'not-applicable', 'undetermined',
                                    'Synthetic fixture only', 'No inference', 'Not clinical', (Candidate('Synthetic fixture label',1),))
            output.validate(request)
            for bad in (replace(output, summary=' '), replace(output, triage_level='routine'),
                        replace(output, candidates=(Candidate('x',2),)),
                        replace(output, candidates=(Candidate('x',1,float('nan')),)),
                        replace(output, candidates=(Candidate('x',1,1.1),)),
                        replace(output, image_quality={999:'poor'})):
                with self.assertRaises(ValueError):
                    bad.validate(request)

    def test_version_mismatch_preserves_existing_database(self):
        wrong = self.path/'legacy.sqlite3'
        from contextlib import closing
        with closing(sqlite3.connect(wrong)) as db:
            db.execute('CREATE TABLE Source(value TEXT)')
            db.execute("INSERT INTO Source VALUES('preserve me')")
            db.commit()
        with self.assertRaisesRegex(RuntimeError,'expected SQLite user_version 4'):
            create_app({**self.config, 'DATABASE':str(wrong)})
        with closing(sqlite3.connect(wrong)) as db:
            self.assertEqual(db.execute('SELECT value FROM Source').fetchone()[0], 'preserve me')

    def test_seed_reset_guard_and_named_demo(self):
        runner = self.app.test_cli_runner()
        self.assertNotEqual(runner.invoke(args=['seed-demo']).exit_code, 0)
        self.assertNotEqual(runner.invoke(args=['reset-demo','--confirm-demo']).exit_code, 0)
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'), 2)
        demo = create_app({**self.config,'DATABASE':str(self.path/'demo.sqlite3')})
        runner = demo.test_cli_runner()
        self.assertEqual(runner.invoke(args=['seed-demo']).exit_code, 0)
        self.assertNotEqual(runner.invoke(args=['seed-demo']).exit_code, 0)
        self.assertNotEqual(runner.invoke(args=['reset-demo']).exit_code, 0)
        self.assertEqual(runner.invoke(args=['reset-demo','--confirm-demo']).exit_code, 0)
        with demo.app_context():
            self.assertEqual(get_db().execute('SELECT count(*) FROM DermCase').fetchone()[0],1)

    def test_locale_scaffolding(self):
        arabic_app = create_app({**self.config, 'APP_LOCALE':'ar'})
        page = arabic_app.test_client().get('/login').get_data(as_text=True)
        self.assertIn('lang="ar" dir="rtl"', page)
        self.assertIn('translations and full RTL verification are pending', page)
        self.assertIn('dir="auto"', self.client.get('/patients/1').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
