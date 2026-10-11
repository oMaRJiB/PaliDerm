"""Credential/role enforcement and the historical additive authentication migration."""
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import check_password_hash
from test_workflow import WorkflowSupport, PASSWORD, ARABIC, TEST_ENCRYPTION_KEY
from app import create_app
from backend.auth import AuthService
from backend.db import ROOT, connect, get_db, migrate_auth
from backend import services as svc


class AuthTests(WorkflowSupport, unittest.TestCase):
    def signup_data(self, **updates):
        data = {'username':'newpatient','password':PASSWORD,'password_confirm':PASSWORD,
                'first_name':'  مريض جديد  ','last_name':'Synthetic','date_of_birth':'2000-02-29'}
        data.update(updates)
        return data

    def test_signup_creates_patient_only_hashed_password_and_login_logout(self):
        self.post('/logout')
        response = self.post('/patients/new', self.signup_data(username='NewPatient'))
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.scalar("SELECT role FROM Account WHERE username='newpatient'"),'patient')
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'),3)
        self.assertEqual(self.scalar('SELECT count(*) FROM Provider'),2)
        stored = self.scalar("SELECT password_hash FROM Account WHERE username='newpatient'")
        self.assertTrue(stored.startswith('scrypt:'))
        self.assertNotIn(PASSWORD,stored)
        self.assertTrue(check_password_hash(stored,PASSWORD))
        with self.client.session_transaction() as session:
            self.assertIn('account_id',session)
            self.assertNotIn('identity',session)
            old_csrf = session['csrf']
        self.assertEqual(self.client.get('/patients/3').status_code,200)
        self.assertEqual(self.post('/logout').status_code,302)
        self.assertEqual(self.client.get('/patients/3').status_code,403)
        self.assertEqual(self.client.get('/queue').status_code,403)
        response = self.post('/login', {'username':'NEWPATIENT','password':PASSWORD})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/patients/3').status_code,200)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session['csrf'],old_csrf)

    def test_duplicate_signup_case_insensitive_has_no_orphan_profile(self):
        self.post('/logout')
        self.assertEqual(self.post('/patients/new',self.signup_data()).status_code,302)
        self.post('/logout')
        before = self.scalar('SELECT count(*) FROM Patient')
        self.assertEqual(self.post('/patients/new',self.signup_data(username='NEWPATIENT')).status_code,409)
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'),before)
        self.assertEqual(self.scalar("SELECT count(*) FROM Account WHERE username='newpatient'"),1)
        with self.client.session_transaction() as session:
            self.assertNotIn('account_id',session)

    def test_wrong_password_unknown_user_and_demo_selector_removed(self):
        self.post('/logout')
        for data in ({'username':'patient1','password':'incorrect-password'},
                     {'username':'unknown','password':PASSWORD}, {'identity':'provider:1'}):
            response = self.post('/login',data)
            self.assertEqual(response.status_code,401)
            self.assertIn('Incorrect username or password',response.get_data(as_text=True))
            with self.client.session_transaction() as session:
                self.assertNotIn('account_id',session)
        page = self.client.get('/login').get_data(as_text=True)
        self.assertNotIn('<select',page)
        self.assertNotIn('Synthetic Clinician',page)
        self.assertNotIn('patient:1',page)
        self.assertNotIn('worker-demo',page)
        with self.client.session_transaction() as session:
            session['identity'] = 'provider:1'
        self.assertEqual(self.client.get('/queue').status_code,403)

    def test_signup_rejects_role_and_record_injection(self):
        self.post('/logout')
        for field,value in [('role','provider'),('role','worker'),('patient_id','1'),('provider_id','1'),('account_id','1')]:
            self.assertEqual(self.post('/patients/new',self.signup_data(**{field:value})).status_code,403)
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'),2)
        self.assertEqual(self.scalar('SELECT count(*) FROM Account'),5)
        page=self.client.get('/patients/new').get_data(as_text=True)
        self.assertNotIn('name="role"',page)
        self.assertNotIn('name="patient_id"',page)

    def test_password_and_username_validation(self):
        self.post('/logout')
        for data in (self.signup_data(password='short',password_confirm='short'),
                     self.signup_data(password_confirm='different-password'),
                     self.signup_data(username='bad user'),self.signup_data(username='مريض'),
                     self.signup_data(password='x'*257,password_confirm='x'*257)):
            self.assertEqual(self.post('/patients/new',data).status_code,400)
        self.assertEqual(self.scalar('SELECT count(*) FROM Patient'),2)

    def test_csrf_for_login_signup_logout_and_rotation(self):
        for url in ('/login','/logout','/patients/new'):
            self.assertEqual(self.client.post(url,data=self.signup_data()).status_code,400)
        self.client.get('/login')
        with self.client.session_transaction() as session:
            old_csrf=session['csrf']
        self.login('provider:1')
        self.assertEqual(self.client.post('/logout',data={'csrf':old_csrf}).status_code,400)
        self.assertEqual(self.client.get('/logout').status_code,405)
        self.assertEqual(self.client.get('/queue').status_code,200)

    def test_real_account_ownership_and_role_navigation(self):
        cid=self.submitted()
        patient_page=self.client.get(f'/cases/{cid}').get_data(as_text=True)
        for href in ('href="/"','href="/my-cases"','href="/cases/new"','action="/logout"'):
            self.assertIn(href,patient_page)
        self.assertNotIn('href="/queue"',patient_page)
        self.login('patient:2')
        for url in ('/patients/1',f'/cases/{cid}','/images/1','/queue'):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.post('/patients/1/cases',{'chief_complaint':ARABIC}).status_code,403)
        self.login('provider:1')
        page=self.client.get('/queue').get_data(as_text=True)
        self.assertIn('href="/queue"',page)
        self.assertNotIn('href="/my-cases"',page)
        self.assertEqual(self.client.get('/cases/new').status_code,403)
        self.login('worker-demo')
        self.assertEqual(self.client.get('/my-cases').status_code,403)
        self.assertNotIn('href="/queue"',self.client.get('/').get_data(as_text=True))

    def test_cli_provisioning_is_separate_and_validates_links(self):
        runner=self.app.test_cli_runner()
        result=runner.invoke(args=['provision-account','--username','operator','--role','worker'],input=PASSWORD+'\n'+PASSWORD+'\n')
        self.assertEqual(result.exit_code,0,result.output)
        self.assertNotIn(PASSWORD,result.output)
        self.assertEqual(self.scalar("SELECT role FROM Account WHERE username='operator'"),'worker')
        result=runner.invoke(args=['provision-account','--username','invalid','--role','provider'],input=PASSWORD+'\n'+PASSWORD+'\n')
        self.assertNotEqual(result.exit_code,0)
        with self.app.app_context():
            with self.assertRaises(svc.Problem):
                AuthService().provision('duplicate-link',PASSWORD,'patient',patient_id=1)
        self.assertEqual(self.scalar("SELECT count(*) FROM Account WHERE username='duplicate-link'"),0)

    def test_deactivated_account_checked_each_request(self):
        self.assertEqual(self.client.get('/patients/1').status_code,200)
        with self.app.app_context(),svc.transaction() as db:
            db.execute("UPDATE Account SET active=0 WHERE username='patient1'")
        self.assertEqual(self.client.get('/patients/1').status_code,403)
        self.post('/logout')
        self.assertEqual(self.login('patient:1').status_code,401)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'existing.sqlite3'
        with closing(connect(self.path)) as db:
            db.executescript((ROOT/'schema.sql').read_text())
            db.execute("INSERT INTO Patient(first_name,last_name) VALUES('عمر','Synthetic')")
            db.execute("INSERT INTO DermCase(patient_id,chief_complaint) VALUES(1,'  شكوى أصلية  ')")
            db.commit()

    def test_additive_migration_backup_records_idempotence_and_startup(self):
        with self.assertRaisesRegex(RuntimeError,'migrate-auth'):
            create_app({'DATABASE':str(self.path),'UPLOAD_DIR':str(self.path.parent/'uploads'),'SECRET_KEY':'test','ENCRYPTION_KEY':TEST_ENCRYPTION_KEY,'ENCRYPTION_KEY_FILE':None})
        backup=migrate_auth(self.path)
        self.assertTrue(backup.is_file())
        with closing(connect(backup)) as old:
            self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(old.execute("SELECT count(*) FROM sqlite_master WHERE name='Account'").fetchone()[0],0)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT chief_complaint FROM DermCase').fetchone()[0],'  شكوى أصلية  ')
            self.assertEqual(db.execute('SELECT count(*) FROM Account').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertIsNone(migrate_auth(self.path))
        with self.assertRaisesRegex(RuntimeError, 'migrate_encryption'):
            create_app({'DATABASE':str(self.path),'UPLOAD_DIR':str(self.path.parent/'uploads'),'SECRET_KEY':'test','ENCRYPTION_KEY':TEST_ENCRYPTION_KEY,'ENCRYPTION_KEY_FILE':None})

    def test_failed_migration_rolls_back_version_and_records(self):
        original=Path.read_text
        def broken_sql(path,*args,**kwargs):
            if path.name=='auth_migration.sql':
                return 'CREATE TABLE Account (broken FOREIGN KEY)'
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',broken_sql),self.assertRaises(sqlite3.Error):
            migrate_auth(self.path)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM Patient').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM sqlite_master WHERE name='Account'").fetchone()[0],0)

    def test_account_schema_blocks_invalid_roles_links_and_cross_entity_ids(self):
        migrate_auth(self.path)
        with closing(connect(self.path)) as db:
            for role,patient,provider in [('provider',1,None),('patient',None,None),('worker',1,None),('patient',999,None)]:
                with self.assertRaises(sqlite3.IntegrityError),db:
                    db.execute('INSERT INTO Account(username,password_hash,role,patient_id,provider_id) VALUES(?,?,?,?,?)',
                               ('invalid','test-hash',role,patient,provider))
