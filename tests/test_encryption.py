"""Authenticated storage, copy migration, key failures and deterministic intake encodings."""
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash
from app import create_app
from backend.db import ROOT, connect, _apply_auth, get_db, initialize
from backend.images import ImageStorage
from backend.migrate_encryption import migrate
from backend.preprocessing import gender_one_hot, normalize_gender, symptom_vector
from backend.security import Cipher, EncryptionError, PREFIX, IMAGE_PREFIX, reveal
from backend import services as svc
from test_workflow import WorkflowSupport, PASSWORD, ARABIC, png, TEST_ENCRYPTION_KEY


class EncryptionTests(WorkflowSupport, unittest.TestCase):
    """Exercise real services against encrypted SQLite/files with synthetic patients."""
    def test_key_required_wrong_key_and_static_uploads_rejected(self):
        for settings in ({'ENCRYPTION_KEY':None}, {'ENCRYPTION_KEY':'bad'},
                         {'ENCRYPTION_KEY':Fernet.generate_key().decode('ascii')}):
            with self.assertRaises(EncryptionError):
                create_app({**self.config, **settings})
        with self.assertRaisesRegex(RuntimeError, 'static'):
            create_app({**self.config, 'UPLOAD_DIR':str(ROOT/'static'/'private-images')})
        with self.assertRaises(EncryptionError):
            Cipher.from_config({'ENCRYPTION_KEY':TEST_ENCRYPTION_KEY,'ENCRYPTION_KEY_FILE':'ignored'})

    def test_gender_choices_encoding_validation_and_symptom_order(self):
        for gender, vector in [('female',[1,0,0]),('male',[0,1,0]),('unknown',[0,0,1])]:
            self.assertEqual(gender_one_hot(gender), vector)
            with self.app.app_context():
                patient_id = svc.create_patient({'first_name':'Synthetic','last_name':'Gender test','sex':gender})
                patient = reveal('Patient',get_db().execute('SELECT * FROM Patient WHERE patient_id=?',(patient_id,)).fetchone())
                self.assertEqual(patient['sex'],gender)
        self.assertEqual(normalize_gender(' Female '),'female')
        self.assertEqual(gender_one_hot(None),[0,0,1])
        for invalid_gender in ('arbitrary input', 1, True, []):
            with self.assertRaises(svc.Problem): normalize_gender(invalid_gender)
        self.assertEqual(symptom_vector({'itching':1,'pain':0}),[1,0,None,None,None,None])
        for invalid in (True, 2, '1'):
            with self.assertRaises(svc.Problem): symptom_vector({'pain':invalid})
        self.post('/logout')
        page = self.client.get('/patients/new').get_data(as_text=True)
        self.assertIn('<select name="sex">',page)
        self.assertNotIn('<input type="text" name="sex"',page)
        response=self.post('/patients/new',{'username':'badgender','password':PASSWORD,'password_confirm':PASSWORD,
                                          'first_name':'Synthetic','last_name':'Test','sex':'invalid'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.scalar("SELECT count(*) FROM Account WHERE username='badgender'"),0)

    def test_at_rest_ciphertext_and_no_plaintext_image_cache(self):
        cid=self.submitted()
        self.claim(cid)
        self.post(f'/cases/{cid}/review',self.review_data())
        with self.app.app_context():
            db=get_db()
            for table, column in [('Patient','first_name'),('DermCase','chief_complaint'),('Symptom','additional_notes'),
                                  ('ProviderReview','clinical_notes'),('ProviderReview','patient_message'),
                                  ('Diagnosis','diagnosis_name'),('TreatmentPlan','instructions')]:
                token=db.execute(f'SELECT {column} FROM {table} LIMIT 1').fetchone()[0]
                self.assertTrue(token.startswith(PREFIX),(table,column))
                self.assertNotIn(ARABIC,token)
            self.assertIsNone(db.execute('SELECT pain FROM Symptom').fetchone()[0])
            self.assertIsNone(db.execute('SELECT duration_days FROM DermCase').fetchone()[0])
            for row in db.execute('SELECT * FROM LesionImage'):
                encrypted=(self.path/'uploads'/row['image_uri']).read_bytes()
                self.assertTrue(encrypted.startswith(IMAGE_PREFIX))
                original=ImageStorage(self.app.config).read_original(row['image_uri'],row['content_sha256'])
                self.assertTrue(original.startswith(b'\x89PNG'))
        raw=(self.path/'test.sqlite3').read_bytes()
        for value in (ARABIC,'PRIVATE CLINICIAN NOTE','Synthetic clinician diagnosis','Synthetic instructions only'):
            self.assertNotIn(value.encode('utf-8'),raw)
        self.assertEqual(len(list((self.path/'uploads').iterdir())),2)

    def test_tamper_fails_closed_after_authorization_and_no_data_logging(self):
        cid=self.submitted()
        with self.app.app_context():
            row=get_db().execute('SELECT * FROM LesionImage LIMIT 1').fetchone()
        path=self.path/'uploads'/row['image_uri']
        path.write_bytes(path.read_bytes()[:-2]+b'xx')
        with patch.object(self.app.logger,'error') as log:
            self.login('patient:2')
            self.assertEqual(self.client.get(f"/images/{row['image_id']}").status_code,403)
            self.login('patient:1')
            response=self.client.get(f"/images/{row['image_id']}")
            self.assertEqual(response.status_code,503)
            self.assertNotIn(ARABIC,response.get_data(as_text=True))
            log.assert_not_called()
        with self.app.app_context(),svc.transaction() as db:
            # Guard permits token-shaped data, but authentication must still reject it.
            db.execute('UPDATE DermCase SET chief_complaint=? WHERE case_id=?',(PREFIX+'corrupt',cid))
        self.assertEqual(self.client.get(f'/cases/{cid}').status_code,503)

    def test_private_service_data_and_unicode_csrf(self):
        cid=self.submitted()
        self.claim(cid)
        self.post(f'/cases/{cid}/review',self.review_data())
        self.login('patient:1')
        with self.app.app_context():
            data=svc.CaseWorkflow({'role':'patient','id':1}).case_details(cid)
            self.assertNotIn('clinical_notes',data['latest'])
            self.assertEqual(data['reviews'],[])
            self.assertEqual(data['analyses'],[])
        self.assertEqual(self.client.post('/logout',data={'csrf':'رمز غير صالح'}).status_code,400)
        self.assertEqual(self.client.get('/patients/1').status_code,200)

    def test_plaintext_writes_and_context_swap_rejected(self):
        cid=self.draft()
        self.details(cid)
        with self.app.app_context():
            encryption=self.app.extensions['cipher']
            with self.assertRaises(EncryptionError): encryption.decrypt('plaintext','Patient.first_name')
            with self.assertRaises(EncryptionError):
                encryption.decrypt(encryption.encrypt('text','Patient.first_name'),'ProviderReview.clinical_notes')
            for sql in ("UPDATE Patient SET phone='plaintext' WHERE patient_id=1",
                        "UPDATE Symptom SET pain=1 WHERE case_id=1",
                        "UPDATE DermCase SET encrypted_duration=NULL WHERE case_id=1"):
                with self.assertRaises(sqlite3.IntegrityError),svc.transaction() as db: db.execute(sql)

    def test_existing_adapter_input_and_decrypted_image_reader(self):
        cid=self.submitted()
        self.login('provider:1')
        with self.app.app_context():
            payload=svc.CaseWorkflow({'role':'provider','id':1}).build_analysis_input(cid)
            self.assertEqual(payload.contract_version,'1.0')
            self.assertEqual(payload.complaint,ARABIC)
            self.assertEqual(payload.sex,'unknown')
            self.assertEqual(gender_one_hot(payload.sex),[0,0,1])
            self.assertEqual(symptom_vector(payload.symptoms)[:2],[None,0])
            storage=ImageStorage(self.app.config)
            for lesion in payload.lesions:
                for image in lesion.images:
                    raw=storage.read_original(image.storage_reference,image.sha256)
                    self.assertEqual(hashlib.sha256(raw).hexdigest(),image.sha256)
        self.assertEqual(self.post(f'/cases/{cid}/analyze',{'analysis_base':'0'}).status_code,503)
        self.assertEqual(self.scalar('SELECT count(*) FROM AIAnalysis'),0)


class EncryptionMigrationTests(unittest.TestCase):
    """Migration publishes only verified encrypted copies and never overwrites sources."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source.sqlite3'
        self.uploads=self.root/'uploads';self.uploads.mkdir()
        self.key_value=Fernet.generate_key();self.key=Cipher(self.key_value)
        raw=png().getvalue();self.storage_id='a'*32+'.png'
        (self.uploads/self.storage_id).write_bytes(raw)
        with closing(connect(self.source)) as db:
            db.executescript((ROOT/'schema.sql').read_text());_apply_auth(db)
            db.execute("INSERT INTO Patient(first_name,last_name,sex) VALUES(?,?,?)",(ARABIC,'Synthetic','  old nonstandard gender  '))
            db.execute("INSERT INTO DermCase(patient_id,chief_complaint,duration_days) VALUES(1,?,7)",(ARABIC,))
            db.execute("INSERT INTO Symptom(case_id,itching,pain,additional_notes) VALUES(1,NULL,0,?)",(ARABIC,))
            db.execute('INSERT INTO Lesion(case_id,body_site_id) VALUES(1,8)')
            db.execute('INSERT INTO LesionImage(lesion_id,image_uri,mime_type,content_sha256) VALUES(1,?,?,?)',
                       (self.storage_id,'image/png',hashlib.sha256(raw).hexdigest()))
            db.execute("INSERT INTO Account(username,password_hash,role,patient_id) VALUES('migrated-patient',?,'patient',1)",
                       (generate_password_hash(PASSWORD,method='scrypt'),))
            db.commit()
        self.original=self.source.read_bytes()

    def test_copy_migration_preserves_records_accounts_gender_archive_and_sources(self):
        dest=self.root/'encrypted'
        report=migrate(self.source,self.uploads,dest,self.key)
        self.assertEqual(report['images'],1)
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertTrue((self.uploads/self.storage_id).read_bytes().startswith(b'\x89PNG'))
        with closing(connect(dest/'demo.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
            patient=db.execute('SELECT * FROM Patient').fetchone()
            self.assertEqual(self.key.reveal('Patient',patient)['sex'],'unknown')
            self.assertEqual(self.key.decrypt(patient['legacy_sex_encrypted'],'Patient.legacy_sex'),'  old nonstandard gender  ')
            self.assertEqual(self.key.reveal('Patient',patient)['first_name'],ARABIC)
            self.assertEqual(self.key.reveal('Symptom',db.execute('SELECT * FROM Symptom').fetchone())['pain'],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('SELECT count(*) FROM Account').fetchone()[0],1)
        self.assertNotIn(ARABIC.encode(),(dest/'demo.sqlite3').read_bytes())
        self.assertTrue((dest/'uploads'/self.storage_id).read_bytes().startswith(IMAGE_PREFIX))
        app=create_app({'TESTING':True,'DATABASE':str(dest/'demo.sqlite3'),'UPLOAD_DIR':str(dest/'uploads'),
                        'SECRET_KEY':'test','ENCRYPTION_KEY':self.key_value,'ENCRYPTION_KEY_FILE':None})
        client=app.test_client();client.get('/login')
        with client.session_transaction() as session: csrf=session['csrf']
        self.assertEqual(client.post('/login',data={'username':'migrated-patient','password':PASSWORD,'csrf':csrf}).status_code,302)
        self.assertIn(ARABIC,client.get('/patients/1').get_data(as_text=True))
        with client.get('/images/1') as response:
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.data,(self.uploads/self.storage_id).read_bytes())
        with self.assertRaises(RuntimeError): migrate(self.source,self.uploads,dest,self.key)

    def test_failure_and_unknown_columns_publish_nothing(self):
        dest=self.root/'failed'
        (self.uploads/self.storage_id).write_bytes(b'changed')
        with self.assertRaises(RuntimeError): migrate(self.source,self.uploads,dest,self.key)
        self.assertFalse(dest.exists())
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual(list(self.root.glob('.encryption-stage-*')),[])
        with closing(connect(self.source)) as db:
            db.execute('ALTER TABLE Patient ADD COLUMN medical_history TEXT');db.commit()
        with self.assertRaisesRegex(RuntimeError,'unmapped columns'):
            migrate(self.source,self.uploads,dest,self.key)
        self.assertFalse(dest.exists())

    def test_known_legacy_gender_and_wrong_destination_key(self):
        with closing(connect(self.source)) as db:
            db.execute("UPDATE Patient SET sex='F'");db.commit()
        dest=self.root/'encrypted'
        migrate(self.source,self.uploads,dest,self.key)
        with closing(connect(dest/'demo.sqlite3')) as db:
            self.assertEqual(self.key.reveal('Patient',db.execute('SELECT * FROM Patient').fetchone())['sex'],'female')
        with self.assertRaises(EncryptionError):
            create_app({'DATABASE':str(dest/'demo.sqlite3'),'UPLOAD_DIR':str(dest/'uploads'),
                        'ENCRYPTION_KEY':Fernet.generate_key().decode(),'ENCRYPTION_KEY_FILE':None})

    def test_failed_fresh_initialization_is_retryable_without_copy_migration(self):
        """A failed new setup may remove its own partial file, never an existing DB."""
        fresh=self.root/'fresh.sqlite3'
        with patch('backend.db.apply_encryption_schema',side_effect=RuntimeError('Synthetic setup failure')):
            with self.assertRaisesRegex(RuntimeError,'Synthetic setup failure'):
                initialize(fresh,self.key)
        self.assertFalse(fresh.exists())
        initialize(fresh,self.key)
        with closing(connect(fresh)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],4)
        before=fresh.read_bytes()
        with self.assertRaises(EncryptionError):
            initialize(fresh,Cipher(Fernet.generate_key()))
        self.assertEqual(fresh.read_bytes(),before)

    def test_existing_destination_cli_reports_launch_guidance_without_overwrite(self):
        """An already migrated target is preserved and explained rather than retried."""
        destination=self.root/'already-encrypted'
        migrate(self.source,self.uploads,destination,self.key)
        before=(destination/'demo.sqlite3').read_bytes()
        environment={**os.environ,'ENCRYPTION_KEY':self.key_value.decode('ascii')}
        environment.pop('ENCRYPTION_KEY_FILE',None)
        result=subprocess.run(
            [sys.executable,'-m','backend.migrate_encryption','--source-db',str(self.source),
             '--source-uploads',str(self.uploads),'--destination',str(destination)],
            capture_output=True,text=True,env=environment,check=False,
        )
        self.assertEqual(result.returncode,1)
        self.assertIn('Destination already exists',result.stderr)
        self.assertIn('launch the encrypted dataset',result.stderr)
        self.assertNotIn('Traceback',result.stderr)
        self.assertEqual((destination/'demo.sqlite3').read_bytes(),before)
        self.assertEqual(self.source.read_bytes(),self.original)

    def test_default_startup_uses_migrated_storage_preserving_plaintext_sources(self):
        """Bare Flask startup must select the encrypted copy, with an explicit key."""
        destination=self.root/'instance'/'encrypted'
        migrate(self.source,self.uploads,destination,self.key)
        legacy=self.root/'instance'/'demo.sqlite3'
        legacy.write_bytes(self.original)
        encrypted_before=(destination/'demo.sqlite3').read_bytes()
        settings={'TESTING':True,'SECRET_KEY':'synthetic-test','ENCRYPTION_KEY':self.key_value}
        # Ignore operator shell paths/keys; all selected storage remains temporary.
        with patch('app.ROOT',self.root),patch.dict(os.environ,{},clear=True):
            application=create_app(settings)
            self.assertEqual(Path(application.config['DATABASE']),(destination/'demo.sqlite3').resolve())
            self.assertEqual(Path(application.config['UPLOAD_DIR']),(destination/'uploads').resolve())
            self.assertEqual(application.test_client().get('/login').status_code,200)
            with self.assertRaises(EncryptionError):
                create_app({**settings,'ENCRYPTION_KEY':Fernet.generate_key()})
            with self.assertRaisesRegex(RuntimeError,'v3'):
                create_app({**settings,'DATABASE':str(legacy)})
        self.assertEqual(legacy.read_bytes(),self.original)
        self.assertEqual(self.source.read_bytes(),self.original)
        self.assertEqual((self.uploads/self.storage_id).read_bytes(),png().getvalue())
        self.assertEqual((destination/'demo.sqlite3').read_bytes(),encrypted_before)

    def test_default_startup_does_not_hide_unmigrated_records_or_generate_a_key(self):
        """Missing migrated storage must not create an empty replacement for legacy data."""
        legacy=self.root/'instance'/'demo.sqlite3'
        legacy.parent.mkdir()
        legacy.write_bytes(self.original)
        with patch('app.ROOT',self.root),patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(RuntimeError,'migrat'):
                create_app({'TESTING':True,'SECRET_KEY':'synthetic-test','ENCRYPTION_KEY':self.key_value})
        self.assertEqual(legacy.read_bytes(),self.original)
        self.assertFalse((legacy.parent/'encrypted'/'demo.sqlite3').exists())
        empty_root=self.root/'fresh-start'
        empty_root.mkdir()
        with patch('app.ROOT',empty_root),patch.dict(os.environ,{},clear=True):
            with self.assertRaises(EncryptionError):
                create_app({'TESTING':True,'SECRET_KEY':'synthetic-test'})
        self.assertFalse((empty_root/'instance'/'encryption.key').exists())
        self.assertFalse((empty_root/'instance'/'encrypted'/'demo.sqlite3').exists())

    def test_duplicate_image_references_preserve_rows_with_one_encrypted_file(self):
        """Several SQL image records may legitimately reference the same source object."""
        with closing(connect(self.source)) as db:
            db.execute('INSERT INTO LesionImage(lesion_id,image_uri,mime_type,content_sha256) '
                       'SELECT lesion_id,image_uri,mime_type,content_sha256 FROM LesionImage')
            db.commit()
        original=self.source.read_bytes()
        destination=self.root/'duplicate-images'
        report=migrate(self.source,self.uploads,destination,self.key)
        self.assertEqual(report['images'],2)
        with closing(connect(destination/'demo.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM LesionImage').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(DISTINCT image_uri) FROM LesionImage').fetchone()[0],1)
        self.assertEqual(len(list((destination/'uploads').iterdir())),1)
        storage=ImageStorage({'UPLOAD_DIR':destination/'uploads','MAX_IMAGE_BYTES':1024*1024,
                              'MAX_IMAGE_COUNT':12},self.key)
        self.assertEqual(storage.read_original(self.storage_id),png().getvalue())
        self.assertEqual(self.source.read_bytes(),original)

    def test_duplicate_image_reference_with_inconsistent_hash_publishes_nothing(self):
        """Deduplicating files must never conceal contradictory SQL content hashes."""
        with closing(connect(self.source)) as db:
            db.execute('INSERT INTO LesionImage(lesion_id,image_uri,mime_type,content_sha256) '
                       "SELECT lesion_id,image_uri,mime_type,? FROM LesionImage",('0'*64,))
            db.commit()
        original=self.source.read_bytes()
        destination=self.root/'inconsistent-images'
        with self.assertRaises(RuntimeError):
            migrate(self.source,self.uploads,destination,self.key)
        self.assertEqual(self.source.read_bytes(),original)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.encryption-stage-*')),[])

    def test_invalid_image_identifier_has_controlled_actionable_cli_failure(self):
        """A legacy URI outside the storage contract must not escape as an HTTP error."""
        with closing(connect(self.source)) as db:
            db.execute("UPDATE LesionImage SET image_uri='../synthetic-invalid.png'")
            db.commit()
        original=self.source.read_bytes()
        destination=self.root/'invalid-image'
        with self.assertRaisesRegex(RuntimeError,'image|storage'):
            migrate(self.source,self.uploads,destination,self.key)
        environment={**os.environ,'ENCRYPTION_KEY':self.key_value.decode('ascii')}
        environment.pop('ENCRYPTION_KEY_FILE',None)
        command=[sys.executable,'-m','backend.migrate_encryption','--source-db',str(self.source),
                 '--source-uploads',str(self.uploads),'--destination',str(destination)]
        result=subprocess.run(command,capture_output=True,text=True,env=environment,check=False)
        self.assertEqual(result.returncode,1)
        self.assertNotIn('Traceback',result.stderr)
        self.assertIn('Migration failed',result.stderr)
        self.assertRegex(result.stderr.lower(),'image|storage')
        self.assertEqual(self.source.read_bytes(),original)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.encryption-stage-*')),[])


if __name__=='__main__':
    unittest.main()
