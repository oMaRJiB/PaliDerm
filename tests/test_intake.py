"""Single-page intake, camera multipart fields and byte-for-byte source retention."""
import hashlib
import io
import unittest
from PIL import Image, PngImagePlugin
from werkzeug.datastructures import MultiDict
from test_workflow import WorkflowSupport, ARABIC, png
from backend.db import get_db
from backend.images import ImageStorage


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


if __name__ == '__main__':
    unittest.main()
