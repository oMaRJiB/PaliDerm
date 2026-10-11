"""Explicitly fictional records and nonclinical geometric demonstration images."""
from io import BytesIO
from pathlib import Path
import os
import re
import secrets
import click
from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage, MultiDict
from backend import services as svc
from backend.db import ROOT, get_db
from backend.auth import AuthService


def guard(app):
    """Restrict destructive demo commands to the explicitly named demo.sqlite3 database."""
    if Path(app.config['DATABASE']).name != 'demo.sqlite3':
        raise click.ClickException('Seed/reset requires a database named demo.sqlite3. No changes made.')


def seed(app):
    """Insert only synthetic records/images through the same encrypted application services."""
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
    workflow = svc.CaseWorkflow(identity)
    case_id = workflow.create_case(a, {'chief_complaint': 'SYNTHETIC demonstration case — geometric image, no clinical inference', 'duration_days': '3'})
    workflow.save_draft(case_id, MultiDict([('chief_complaint', 'SYNTHETIC demonstration case — geometric image, no clinical inference'),
                                     ('duration_days', '3'), ('itching', '1'), ('pain', '0'), ('body_sites', '7'),
                                     ('additional_notes', 'Fictional intake only.')]))
    lesion_id = get_db().execute('SELECT lesion_id FROM Lesion WHERE case_id=?', (case_id,)).fetchone()[0]
    im = Image.new('RGB', (320, 240), '#dddddd')
    draw = ImageDraw.Draw(im)
    draw.rectangle((50, 50, 270, 190), outline='#333333', width=4)
    draw.text((60, 100), 'SYNTHETIC DEMO - NOT SKIN', fill='#000000')
    stream = BytesIO()
    im.save(stream, format='PNG')
    stream.seek(0)
    workflow.upload_images(case_id, lesion_id, [FileStorage(stream=stream, filename='synthetic.png')])
    workflow.submit_case(case_id, {'consent': '1'})


def reset(app, *, purge_images=False, create_test_accounts=False):
    """Reset synthetic runtime data, optionally removing generated demo images.

    Purging is restricted to the database's dedicated sibling uploads directory;
    keys, source attachments, models, unknown files and other databases survive.
    Stop the server first: resetting a live clinical workflow is unsupported.
    """
    guard(app)
    uploads = Path(app.config['UPLOAD_DIR'])
    if purge_images and uploads.resolve() != (Path(app.config['DATABASE']).parent / 'uploads').resolve():
        raise click.ClickException('Image purge requires the demo database sibling uploads directory. No changes made.')
    old_images = [path for path in uploads.iterdir()
                  if re.fullmatch(r'[a-f0-9]{32}\.(png|jpg)', path.name)
                  and path.is_file() and not path.is_symlink()] if purge_images else []
    db = get_db()
    # Explicit demo-only transactional clearing. Schema/source and other databases preserved.
    with svc.transaction() as db:
        for table in ('Account', 'TreatmentPlan', 'Diagnosis', 'ProviderReview', 'AICandidate', 'AIAnalysis',
                      'LesionImage', 'Lesion', 'Symptom', 'DermCase', 'Provider', 'Patient'):
            db.execute(f'DELETE FROM {table}')
    # Remove only the pre-reset generated files, never freshly seeded images.
    for path in old_images:
        path.unlink(missing_ok=True)
    keypath = ROOT / 'instance/session.key'
    if keypath.is_file() and app.secret_key == keypath.read_text(encoding='utf-8'):
        # Account IDs are reused by reset. Invalidate old signed browser cookies
        # before newly seeded accounts can inherit the same IDs on restart.
        keypath.write_text(secrets.token_hex(32), encoding='utf-8')
        keypath.chmod(0o600)
    seed(app)
    if create_test_accounts:
        credentials = ['LOCAL SYNTHETIC DEMO ONLY — plaintext passwords; do not share or commit.',
                       'URL: http://127.0.0.1:5000/login', '']
        auth = AuthService()
        for username, role, patient_id, provider_id in (
            ('patient1', 'patient', 1, None), ('patient2', 'patient', 2, None),
            ('clinician1', 'provider', None, 1), ('clinician2', 'provider', None, 2),
            ('worker1', 'worker', None, None),
        ):
            password = secrets.token_urlsafe(18)
            auth.provision(username, password, role, patient_id, provider_id)
            credentials.append(f'{username} | {password} | {role}')
        credentials.append('\nWorker login exists; assisted submission remains unavailable.')
        path = ROOT / 'instance/test-accounts.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refuse a symlink and enforce private permissions before writing secrets.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            os.fchmod(file.fileno(), 0o600)
            file.write('\n'.join(credentials) + '\n')
