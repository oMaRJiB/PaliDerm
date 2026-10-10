"""Explicitly fictional records and nonclinical geometric demonstration images."""
from io import BytesIO
from pathlib import Path
import click
from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage, MultiDict
from backend import services as svc
from backend.db import get_db, initialize


def guard(app):
    if Path(app.config['DATABASE']).name != 'demo.sqlite3':
        raise click.ClickException('Seed/reset requires a database named demo.sqlite3. No changes made.')


def seed(app):
    guard(app)
    db = get_db()
    if db.execute('SELECT 1 FROM Patient').fetchone() or db.execute('SELECT 1 FROM Provider').fetchone():
        raise click.ClickException('Demo database is not empty. Existing data preserved; use reset-demo --confirm-demo deliberately.')
    a = svc.create_patient({'first_name': 'Synthetic', 'last_name': 'Patient A', 'date_of_birth': '1990-01-15', 'phone': '+1-202-555-0101', 'email': 'patient-a@example.test'})
    svc.create_patient({'first_name': 'مريض تجريبي', 'last_name': 'Patient B', 'date_of_birth': '2001-02-03', 'phone': '+1-202-555-0102'})
    with svc.transaction() as db:
        db.execute("INSERT INTO Provider(name,specialty) VALUES('Synthetic Clinician A','Demo dermatology')")
        db.execute("INSERT INTO Provider(name,specialty) VALUES('Synthetic Clinician B','Demo primary care')")
    identity = {'role': 'patient', 'id': a}
    case_id = svc.create_case(a, {'chief_complaint': 'SYNTHETIC demonstration case — geometric image, no clinical inference', 'duration_days': '3'}, identity)
    svc.save_draft(case_id, MultiDict([('chief_complaint', 'SYNTHETIC demonstration case — geometric image, no clinical inference'),
                                     ('duration_days', '3'), ('itching', '1'), ('pain', '0'), ('body_sites', '7'),
                                     ('additional_notes', 'Fictional intake only.')]), identity)
    lesion_id = get_db().execute('SELECT lesion_id FROM Lesion WHERE case_id=?', (case_id,)).fetchone()[0]
    im = Image.new('RGB', (320, 240), '#dddddd')
    draw = ImageDraw.Draw(im)
    draw.rectangle((50, 50, 270, 190), outline='#333333', width=4)
    draw.text((60, 100), 'SYNTHETIC DEMO - NOT SKIN', fill='#000000')
    stream = BytesIO()
    im.save(stream, format='PNG')
    stream.seek(0)
    svc.upload_images(case_id, lesion_id, [FileStorage(stream=stream, filename='synthetic.png')], identity)
    svc.submit_case(case_id, {'consent': '1'}, identity)


def reset(app):
    guard(app)
    db = get_db()
    # Explicit demo-only transactional clearing. Schema/source and other databases preserved.
    with svc.transaction() as db:
        for table in ('TreatmentPlan', 'Diagnosis', 'ProviderReview', 'AICandidate', 'AIAnalysis',
                      'LesionImage', 'Lesion', 'Symptom', 'DermCase', 'Provider', 'Patient'):
            db.execute(f'DELETE FROM {table}')
    seed(app)
