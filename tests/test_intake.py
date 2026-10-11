"""Single-page intake, camera multipart fields and byte-for-byte source retention."""
import hashlib
import io
import json
import unittest
from datetime import date
from PIL import Image, PngImagePlugin
from werkzeug.datastructures import MultiDict
from test_workflow import WorkflowSupport, ARABIC, png
from backend.db import get_db
from backend.images import ImageStorage
from backend.preprocessing import SCINQuestionnaire, checkbox_answers
from backend.security import PREFIX, reveal
from backend.validation import Problem


def patient_questionnaire(**updates):
    """Explicitly answered synthetic checkbox groups; no inferred absent symptoms."""
    values = {'chief_complaint': ARABIC, 'additional_notes': ARABIC, 'body_sites': '8',
              'photo_body_site': '8', 'intake_action': 'save', 'symptom_ui': 'checkboxes-v1',
              'symptoms_answered': '1', 'itching': '1', 'model_questionnaire_version': '1',
              'model_textures_rough_or_flaky': '1', 'model_body_parts_palm': '1',
              'model_other_symptoms_no_relevant_symptoms': '1',
              'model_fitzpatrick_skin_type': 'UNKNOWN', 'model_related_category': 'RASH',
              'model_condition_duration': 'ONE_TO_FOUR_WEEKS'}
    values.update({'model_group_answered_' + group: '1' for group in SCINQuestionnaire.GROUPS})
    values.update(updates)
    return MultiDict(values)


class IntakeTests(WorkflowSupport, unittest.TestCase):
    def values(self, **updates):
        data = {'chief_complaint': ARABIC, 'duration_days': '0', 'itching': '', 'pain': '0',
                'body_sites': '8', 'photo_body_site': '8', 'intake_action': 'submit', 'consent': '1'}
        data.update(updates)
        return MultiDict(data)

    def test_camera_and_file_intake_atomic_submission_and_retry(self):
        cid = self.draft()
        data = self.values()
        data.add('images', (png(), 'existing.png'))
        data.add('camera', (png(), 'camera.png'))
        self.assertEqual(self.post(f'/cases/{cid}/intake', data).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'submitted')
        self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 2)
        self.assertIsNone(self.field('Symptom', 'itching'))
        self.assertEqual(self.field('Symptom', 'pain'), 0)
        self.assertEqual(self.field('DermCase', 'duration_days'), 0)
        stamp = self.scalar('SELECT consent_at FROM DermCase')
        retry = self.values()
        retry.add('camera', (png(), 'duplicate.png'))
        self.assertEqual(self.post(f'/cases/{cid}/intake', retry).status_code, 302)
        self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 2)
        self.assertEqual(self.scalar('SELECT consent_at FROM DermCase'), stamp)
        self.claim(cid)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 302)
        self.login('patient:1')
        self.assertIn('Synthetic clinician diagnosis', self.client.get(f'/cases/{cid}').get_data(as_text=True))

    def test_invalid_consent_or_photo_rolls_back_details_and_files(self):
        cid = self.draft()
        for bad in ('consent', 'image', 'site'):
            data = self.values(consent='0' if bad == 'consent' else '1', photo_body_site='7' if bad == 'site' else '8')
            data.add('images', (png(), 'valid.png'))
            if bad == 'image':
                data.add('camera', (io.BytesIO(b'broken'), 'invalid.jpg'))
            self.assertEqual(self.post(f'/cases/{cid}/intake', data).status_code, 400)
            self.assertEqual(self.scalar('SELECT count(*) FROM Symptom'), 0)
            self.assertEqual(self.scalar('SELECT count(*) FROM Lesion'), 0)
            self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 0)
            self.assertEqual(list((self.path/'uploads').iterdir()), [])
            self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'draft')
        self.login('patient:2')
        self.assertEqual(self.post(f'/cases/{cid}/intake', self.values()).status_code, 403)

    def test_draft_without_photos_and_all_sections_visible(self):
        cid = self.draft()
        page = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        for field in ('chief_complaint','itching','body_sites','photo_body_site','images','camera','consent'):
            self.assertIn(f'name="{field}"', page)
        self.assertIn('capture="environment"', page)
        self.assertNotIn(f'Case {cid}</', page)
        self.assertNotIn('pixels per image', page)
        self.assertEqual(self.post(f'/cases/{cid}/intake', self.values(intake_action='save', consent='')).status_code, 302)
        self.assertEqual(self.scalar('SELECT status FROM DermCase'), 'draft')
        self.assertIsNone(self.scalar('SELECT consent_at FROM DermCase'))

    def test_exact_jpeg_exif_and_png_metadata_persist_after_restart(self):
        cid = self.draft()
        image = Image.new('RGB', (80, 60), 'gray')
        exif = Image.Exif()
        exif[271] = 'Synthetic camera manufacturer'
        exif[274] = 6
        exif[34853] = {1: 'N', 2: (1.0, 2.0, 3.0), 3: 'E', 4: (4.0, 5.0, 6.0)}
        jpeg = io.BytesIO(); image.save(jpeg, format='JPEG', exif=exif)
        info = PngImagePlugin.PngInfo(); info.add_text('Comment', 'Synthetic metadata — بيانات')
        png_data = io.BytesIO(); image.save(png_data, format='PNG', pnginfo=info)
        originals = [jpeg.getvalue(), png_data.getvalue()]
        data = self.values()
        data.add('camera', (io.BytesIO(originals[0]), 'phone.jpg'))
        data.add('images', (io.BytesIO(originals[1]), 'existing.png'))
        # Old custom configuration is ignored; there is no app-level pixel rejection.
        self.app.config['MAX_IMAGE_PIXELS'] = 1
        self.assertEqual(self.post(f'/cases/{cid}/intake', data).status_code, 302)
        with self.app.app_context():
            rows = get_db().execute('SELECT * FROM LesionImage ORDER BY image_id').fetchall()
            for row in rows:
                stored = ImageStorage(self.app.config).read_original(row['image_uri'], row['content_sha256'])
                self.assertNotEqual(stored, (self.path/'uploads'/row['image_uri']).read_bytes())
                self.assertIn(stored, originals)
                self.assertEqual(hashlib.sha256(stored).hexdigest(), row['content_sha256'])
                with Image.open(io.BytesIO(stored)) as decoded:
                    if row['mime_type'] == 'image/jpeg':
                        self.assertEqual(decoded.getexif()[271], 'Synthetic camera manufacturer')
                        self.assertEqual(decoded.getexif()[274], 6)
                        self.assertEqual(decoded.getexif().get_ifd(34853)[1], 'N')
                    else:
                        self.assertIn('بيانات', decoded.info['Comment'])
        from app import create_app
        restarted = create_app(self.config).test_client()
        restarted.get('/login')
        from test_workflow import PASSWORD
        with restarted.session_transaction() as session: csrf = session['csrf']
        restarted.post('/login', data={'username':'patient1','password':PASSWORD,'csrf':csrf})
        for row in rows:
            with restarted.get(f"/images/{row['image_id']}") as response:
                self.assertEqual(response.status_code, 200)
                self.assertIn(response.data, originals)


class PatientQuestionnaireTests(WorkflowSupport, unittest.TestCase):
    """Patient-owned encrypted extras, profile derivations and checkbox semantics."""

    def test_patient_controls_are_checkboxes_with_profile_context_and_duration_ranges(self):
        from test_local_model_adapter import FormControls
        cid = self.draft()
        html = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        controls = FormControls(html)
        self.assertEqual(controls.inputs['itching']['type'], 'checkbox')
        self.assertEqual(controls.inputs['model_textures_flat']['type'], 'checkbox')
        self.assertIn('model_condition_duration', controls.selects)
        self.assertNotIn('itching', controls.selects)
        self.assertNotIn('model_age_group', controls.selects)
        self.assertNotIn('model_sex_at_birth', controls.inputs)
        self.assertIn('18–29 years', html)
        self.assertIn('Unknown / Prefer not to say', html)
        self.assertIn('ONE_TO_FOUR_WEEKS', html)
        self.assertNotIn('name="duration_days"', html)
        self.assertIn('capture="environment"', html)

    def test_encrypted_extra_answers_and_arabic_survive_restart_and_prefill(self):
        from app import create_app
        cid = self.draft()
        self.assertEqual(self.post(f'/cases/{cid}/intake', patient_questionnaire()).status_code, 302)
        answers = self.field('Symptom', 'model_metadata')
        self.assertEqual(len(answers), 36)
        self.assertEqual(answers['textures_rough_or_flaky'], 1)
        self.assertEqual(answers['textures_flat'], 0)
        self.assertEqual(answers['condition_symptoms_itching'], 1)
        self.assertEqual(answers['other_symptoms_fever'], 0)
        self.assertEqual(answers['age_group'], 'AGE_18_TO_29')
        self.assertEqual(answers['sex_at_birth'], 'OTHER_OR_UNSPECIFIED')
        self.assertEqual(answers['condition_duration'], 'ONE_TO_FOUR_WEEKS')
        self.assertIsNone(self.field('DermCase', 'duration_days'))
        self.assertTrue(self.scalar('SELECT encrypted_answers FROM Symptom').startswith(PREFIX))
        self.assertNotIn('ONE_TO_FOUR_WEEKS', self.scalar('SELECT encrypted_answers FROM Symptom'))
        restarted = create_app(self.config)
        with restarted.app_context():
            db = get_db()
            symptom = reveal('Symptom', db.execute('SELECT * FROM Symptom').fetchone())
            self.assertEqual(symptom['model_metadata'], answers)
            self.assertEqual(symptom['additional_notes'], ARABIC)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 4)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        html = self.client.get(f'/cases/{cid}').get_data(as_text=True)
        self.assertIn('name="model_textures_rough_or_flaky" value="1" checked', html)
        self.assertIn('value="ONE_TO_FOUR_WEEKS" selected', html)

    def test_unconfirmed_groups_preserve_unknown_and_do_not_block_manual_submission(self):
        cid = self.draft()
        form = patient_questionnaire(intake_action='submit', consent='1')
        for key in ('symptoms_answered', 'model_group_answered_textures', 'model_group_answered_systemic'):
            form.pop(key)
        form.add('images', (png(), 'synthetic.png'))
        self.assertEqual(self.post(f'/cases/{cid}/intake', form).status_code, 302)
        self.assertEqual(self.field('Symptom', 'itching'), 1)
        self.assertIsNone(self.field('Symptom', 'pain'))
        answers = self.field('Symptom', 'model_metadata')
        self.assertIsNone(answers['textures_flat'])
        self.assertIsNone(answers['other_symptoms_fever'])
        self.assertEqual(answers['textures_rough_or_flaky'], 1)
        self.claim(cid)
        self.assertEqual(self.post(f'/cases/{cid}/review', self.review_data()).status_code, 302)

    def test_invalid_or_spoofed_answers_roll_back_the_entire_intake(self):
        cid = self.draft()
        invalid = [patient_questionnaire(model_age_group='AGE_70_TO_79'),
                   patient_questionnaire(model_sex_at_birth='MALE'),
                   patient_questionnaire(model_condition_duration='14'),
                   patient_questionnaire(model_textures_flat='0'),
                   patient_questionnaire(model_condition_symptoms_no_relevant_experience='1')]
        duplicate = patient_questionnaire()
        duplicate.add('model_textures_flat', '1')
        duplicate.add('model_textures_flat', '1')
        invalid.append(duplicate)
        for form in invalid:
            form.add('images', (png(), 'should-rollback.png'))
            self.assertEqual(self.post(f'/cases/{cid}/intake', form).status_code, 400)
            self.assertEqual(self.scalar('SELECT count(*) FROM Symptom'), 0)
            self.assertEqual(self.scalar('SELECT count(*) FROM LesionImage'), 0)
            self.assertEqual(list((self.path/'uploads').iterdir()), [])

    def test_ownership_csrf_and_submitted_freeze_cover_new_answers(self):
        cid = self.draft()
        self.login('patient:2')
        self.assertEqual(self.post(f'/cases/{cid}/intake', patient_questionnaire()).status_code, 403)
        self.login('patient:1')
        self.assertEqual(self.client.post(f'/cases/{cid}/intake', data=patient_questionnaire()).status_code, 400)
        form = patient_questionnaire(intake_action='submit', consent='1')
        form.add('images', (png(), 'synthetic.png'))
        self.assertEqual(self.post(f'/cases/{cid}/intake', form).status_code, 302)
        original = self.field('Symptom', 'model_metadata')
        self.assertEqual(self.post(f'/cases/{cid}/intake', patient_questionnaire(model_textures_flat='1')).status_code, 409)
        retry = patient_questionnaire(intake_action='submit', consent='1', model_textures_flat='1')
        self.assertEqual(self.post(f'/cases/{cid}/intake', retry).status_code, 302)
        self.assertEqual(self.field('Symptom', 'model_metadata'), original)
        self.assertNotIn('name="model_', self.client.get(f'/cases/{cid}').get_data(as_text=True))

    def test_legacy_cases_keep_unknowns_and_legacy_posts_preserve_saved_extras(self):
        cid = self.draft()
        self.details(cid)
        with self.app.app_context():
            legacy = reveal('Symptom', get_db().execute('SELECT * FROM Symptom').fetchone())
            self.assertNotIn('model_metadata', legacy)
        self.assertIsNone(self.field('Symptom', 'itching'))
        self.assertEqual(self.post(f'/cases/{cid}/intake', patient_questionnaire()).status_code, 302)
        original = self.field('Symptom', 'model_metadata')
        self.details(cid, itching='1', pain='0', bleeding='0', fever='0')
        self.assertEqual(self.field('Symptom', 'model_metadata'), original)


class QuestionnaireEncodingTests(unittest.TestCase):
    """Pure demographic/checkbox transforms, including trained range boundaries."""

    def test_profile_age_bands_and_sex_categories(self):
        reference = date(2026, 10, 11)
        for age, expected in ((17, 'AGE_UNKNOWN'), (18, 'AGE_18_TO_29'), (29, 'AGE_18_TO_29'),
                              (30, 'AGE_30_TO_39'), (69, 'AGE_60_TO_69'), (70, 'AGE_70_TO_79'),
                              (79, 'AGE_70_TO_79'), (80, 'AGE_UNKNOWN')):
            birthday = date(reference.year-age, reference.month, reference.day).isoformat()
            self.assertEqual(SCINQuestionnaire.profile_values({'date_of_birth': birthday, 'sex': 'female'}, reference),
                             {'age_group': expected, 'sex_at_birth': 'FEMALE'})
        self.assertEqual(SCINQuestionnaire.profile_values({'date_of_birth': None, 'sex': 'unknown'}, reference),
                         {'age_group': 'AGE_UNKNOWN', 'sex_at_birth': 'OTHER_OR_UNSPECIFIED'})
        self.assertEqual(SCINQuestionnaire.demographic_values(35, 'male')['sex_at_birth'], 'MALE')
        # A birthday tomorrow has not happened yet; do not round age upward.
        self.assertEqual(SCINQuestionnaire.profile_values({'date_of_birth': '1996-10-12', 'sex': 'male'}, reference)['age_group'], 'AGE_18_TO_29')

    def test_checkbox_no_requires_group_confirmation_and_rejects_duplicates(self):
        self.assertEqual(checkbox_answers(MultiDict(), ['a', 'b'], 'done'), {'a': None, 'b': None})
        self.assertEqual(checkbox_answers(MultiDict({'a':'1'}), ['a', 'b'], 'done'), {'a': 1, 'b': None})
        self.assertEqual(checkbox_answers(MultiDict({'done':'1'}), ['a', 'b'], 'done'), {'a': 0, 'b': 0})
        self.assertEqual(checkbox_answers(MultiDict(), ['a', 'b'], 'done', previous={'a':0}), {'a':0, 'b':None})
        with self.assertRaises(Problem):
            checkbox_answers(MultiDict([('a', '1'), ('a', '1')]), ['a'], 'done')


if __name__ == '__main__':
    unittest.main()
