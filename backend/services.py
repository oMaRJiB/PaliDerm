"""Validation and transactional workflow; all writes are role/ownership checked."""
import hashlib
import io
import re
import sqlite3
import warnings
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from flask import current_app
from backend.db import get_db
from backend.ai.adapter import AnalysisInput, ImageInput, LesionInput

SYMPTOMS = ('itching', 'pain', 'bleeding', 'discharge', 'fever', 'rapidly_worsening')
STATUSES = ('draft', 'submitted', 'in_review', 'needs_information', 'reviewed', 'closed')
DECISIONS = ('confirmed', 'modified', 'needs_information', 'referred', 'inconclusive')
TRIAGE = ('red', 'amber', 'green', 'undetermined')
CONSENT_VERSION = 'local-demo-v1'


class Problem(Exception):
    def __init__(self, key, status=400):
        self.key, self.status = key, status


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def required(value):
    if not isinstance(value, str) or not value.strip():
        raise Problem('required')
    return value  # validate without normalizing the user's text


def calendar(value, birth=False):
    if not value:
        return None
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError()
        parsed = date.fromisoformat(value)
        if birth and parsed > datetime.now(timezone.utc).date():
            raise ValueError()
    except (ValueError, TypeError):
        raise Problem('invalid_date') from None
    return value


def integer(value):
    if value == '' or value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+', value) or len(value) > 8:
        raise Problem('invalid_duration')
    return int(value)


def choice(value, allowed):
    if value not in allowed:
        raise Problem('invalid_choice')
    return value


@contextmanager
def transaction():
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


def role(identity, expected):
    if not identity or identity['role'] != expected:
        raise Problem('forbidden', 403)


def patient_access(patient_id, identity, db=None):
    db = db or get_db()
    row = db.execute('SELECT * FROM Patient WHERE patient_id=?', (patient_id,)).fetchone()
    if not row:
        raise Problem('not_found', 404)
    if not identity or identity['role'] != 'patient' or identity['id'] != patient_id:
        raise Problem('forbidden', 403)
    return row


def case_access(case_id, identity, db=None):
    db = db or get_db()
    row = db.execute('SELECT * FROM DermCase WHERE case_id=?', (case_id,)).fetchone()
    if not row:
        raise Problem('not_found', 404)
    if identity and identity['role'] == 'patient' and identity['id'] == row['patient_id']:
        return row
    if identity and identity['role'] == 'provider' and row['status'] != 'draft' and (
        row['provider_id'] is None or row['provider_id'] == identity['id']
    ):
        return row
    raise Problem('forbidden', 403)


def draft_access(case_id, identity, db):
    role(identity, 'patient')
    row = case_access(case_id, identity, db)
    if row['status'] != 'draft':
        raise Problem('transition', 409)
    return row


def create_patient(form):
    values = [required(form.get('first_name')), required(form.get('last_name')),
              calendar(form.get('date_of_birth'), birth=True)]
    values += [form.get(k) or None for k in ('sex', 'phone', 'email')]
    with transaction() as db:
        return db.execute('INSERT INTO Patient(first_name,last_name,date_of_birth,sex,phone,email) '
                          'VALUES(?,?,?,?,?,?)', values).lastrowid


def create_case(patient_id, form, identity):
    complaint = required(form.get('chief_complaint'))
    duration = integer(form.get('duration_days'))
    with transaction() as db:
        patient_access(patient_id, identity, db)
        return db.execute('INSERT INTO DermCase(patient_id,chief_complaint,duration_days) VALUES(?,?,?)',
                          (patient_id, complaint, duration)).lastrowid


def save_draft(case_id, form, identity):
    complaint = required(form.get('chief_complaint'))
    duration = integer(form.get('duration_days'))
    symptoms = []
    for key in SYMPTOMS:
        answer = form.get(key, '')
        if answer not in ('', '0', '1'):
            raise Problem('invalid_boolean')
        symptoms.append(None if answer == '' else int(answer))
    try:
        sites = {int(x) for x in form.getlist('body_sites')}
    except (ValueError, TypeError):
        raise Problem('invalid_choice') from None
    with transaction() as db:
        draft_access(case_id, identity, db)
        valid = {r[0] for r in db.execute('SELECT body_site_id FROM BodySite')}
        if not sites <= valid:
            raise Problem('invalid_choice')
        lesions = db.execute('SELECT * FROM Lesion WHERE case_id=?', (case_id,)).fetchall()
        for lesion in lesions:
            if lesion['body_site_id'] not in sites:
                if db.execute('SELECT 1 FROM LesionImage WHERE lesion_id=?', (lesion['lesion_id'],)).fetchone():
                    raise Problem('site_image')
                db.execute('DELETE FROM Lesion WHERE lesion_id=?', (lesion['lesion_id'],))
        existing = {r['body_site_id'] for r in lesions}
        for site in sorted(sites - existing):
            db.execute('INSERT INTO Lesion(case_id,body_site_id) VALUES(?,?)', (case_id, site))
        db.execute('UPDATE DermCase SET chief_complaint=?,duration_days=? WHERE case_id=?',
                   (complaint, duration, case_id))
        db.execute('INSERT INTO Symptom(case_id,itching,pain,bleeding,discharge,fever,rapidly_worsening,additional_notes) '
                   'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET '
                   'itching=excluded.itching,pain=excluded.pain,bleeding=excluded.bleeding,'
                   'discharge=excluded.discharge,fever=excluded.fever,rapidly_worsening=excluded.rapidly_worsening,'
                   'additional_notes=excluded.additional_notes',
                   (case_id, *symptoms, form.get('additional_notes') or None))


def normalize_image(upload):
    limit = current_app.config['MAX_IMAGE_BYTES']
    raw = upload.stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise Problem('bad_image')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in ('JPEG', 'PNG') or getattr(im, 'n_frames', 1) != 1:
                    raise ValueError()
                if im.width * im.height > current_app.config['MAX_IMAGE_PIXELS']:
                    raise ValueError()
                im.load()
                oriented = ImageOps.exif_transpose(im).convert('RGB')
                # Copy pixel data into a clean image: no EXIF, ICC, comments or location data.
                clean = Image.new('RGB', oriented.size)
                clean.paste(oriented)
                output = io.BytesIO()
                clean.save(output, format='PNG')
                data = output.getvalue()
                if len(data) > limit:
                    raise ValueError()
                return data
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Problem('bad_image') from None


def upload_images(case_id, lesion_id, uploads, identity):
    paths = []
    try:
        with transaction() as db:
            draft_access(case_id, identity, db)
            if not db.execute('SELECT 1 FROM Lesion WHERE lesion_id=? AND case_id=?', (lesion_id, case_id)).fetchone():
                raise Problem('invalid_choice')
            uploads = [u for u in uploads if u.filename]
            if not uploads:
                raise Problem('bad_image')
            count = db.execute('SELECT count(*) FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE l.case_id=?',
                               (case_id,)).fetchone()[0]
            if count + len(uploads) > current_app.config['MAX_IMAGE_COUNT']:
                raise Problem('image_count')
            for upload in uploads:
                data = normalize_image(upload)
                storage_id = uuid4().hex + '.png'
                path = Path(current_app.config['UPLOAD_DIR']) / storage_id
                paths.append(path)
                with path.open('xb') as file:
                    file.write(data)
                db.execute('INSERT INTO LesionImage(lesion_id,image_uri,mime_type,content_sha256) VALUES(?,?,?,?)',
                           (lesion_id, storage_id, 'image/png', hashlib.sha256(data).hexdigest()))
    except BaseException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def submit_case(case_id, form, identity):
    with transaction() as db:
        role(identity, 'patient')
        row = case_access(case_id, identity, db)
        # Repeated submit never changes consent/time, queues AI, or writes another case.
        if row['status'] != 'draft':
            if row['submitted_at']:
                return False
            raise Problem('transition', 409)
        if form.get('consent') != '1' or not row['chief_complaint'].strip() or not (
            db.execute('SELECT 1 FROM Symptom WHERE case_id=?', (case_id,)).fetchone()
            and db.execute('SELECT 1 FROM Lesion WHERE case_id=?', (case_id,)).fetchone()
            and db.execute('SELECT 1 FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE l.case_id=?',
                           (case_id,)).fetchone()
        ):
            raise Problem('submit_required')
        for image in db.execute('SELECT i.* FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE l.case_id=?', (case_id,)):
            path = Path(current_app.config['UPLOAD_DIR']) / image['image_uri']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != image['content_sha256']:
                raise Problem('storage', 409)
        stamp = now()
        db.execute("UPDATE DermCase SET status='submitted',submitted_at=?,consent_at=?,consent_version=? WHERE case_id=?",
                   (stamp, stamp, CONSENT_VERSION, case_id))
        return True


def transition(case_id, action, identity):
    role(identity, 'provider')
    with transaction() as db:
        row = case_access(case_id, identity, db)
        targets = {'claim': ('submitted', 'in_review'), 'revise': ('reviewed', 'in_review'), 'close': ('reviewed', 'closed')}
        if action not in targets or row['status'] != targets[action][0]:
            raise Problem('transition', 409)
        if action != 'claim' and row['provider_id'] != identity['id']:
            raise Problem('forbidden', 403)
        if action in ('revise', 'close') and not db.execute('SELECT 1 FROM ProviderReview WHERE case_id=?', (case_id,)).fetchone():
            raise Problem('transition', 409)
        db.execute('UPDATE DermCase SET status=?,provider_id=? WHERE case_id=?',
                   (targets[action][1], identity['id'], case_id))


def publish_review(case_id, form, identity):
    role(identity, 'provider')
    decision = choice(form.get('decision'), DECISIONS)
    triage = choice(form.get('triage_level'), TRIAGE)
    message = required(form.get('patient_message'))
    followup = calendar(form.get('followup_date'))
    referral = choice(form.get('referral_required', '0'), ('0', '1')) == '1'
    destination, reason = form.get('referral_destination') or None, form.get('referral_reason') or None
    if (decision == 'referred' and not referral) or (referral and (not destination or not destination.strip() or not reason or not reason.strip())):
        raise Problem('referral_validation')
    if not referral and (destination or reason):
        raise Problem('referral_validation')
    diagnoses = []
    primary = form.get('primary', '0')
    if primary not in ('0', '1', '2'):
        raise Problem('review_diagnosis')
    for index in range(3):
        name = form.get(f'diagnosis_{index}', '')
        certainty = choice(form.get(f'certainty_{index}', 'provisional'), ('provisional', 'confirmed'))
        medication, dosage, instructions = (form.get(f'{k}_{index}', '') for k in ('medication', 'dosage', 'instructions'))
        if name and not name.strip():
            raise Problem('required')
        if any((medication, dosage, instructions)) and (not name or not instructions.strip()):
            raise Problem('treatment_diagnosis')
        if name:
            diagnoses.append((name, certainty, int(primary == str(index)), medication or None, dosage or None, instructions or None))
    if (decision in ('confirmed', 'modified') and not diagnoses) or (diagnoses and sum(d[2] for d in diagnoses) != 1):
        raise Problem('review_diagnosis')
    with transaction() as db:
        row = case_access(case_id, identity, db)
        if row['provider_id'] != identity['id']:
            raise Problem('forbidden', 403)
        if row['status'] != 'in_review':
            raise Problem('transition', 409)
        latest_id = db.execute('SELECT coalesce(max(review_id),0) FROM ProviderReview WHERE case_id=?', (case_id,)).fetchone()[0]
        if str(latest_id) != form.get('review_base', '0'):
            raise Problem('conflict', 409)
        # AI linkage deliberately optional; manual review has analysis_id NULL.
        review_id = db.execute('INSERT INTO ProviderReview(case_id,provider_id,reviewed_at,decision,triage_level,'
                              'clinical_notes,patient_message,referral_required,referral_destination,referral_reason,followup_date) '
                              'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                              (case_id, identity['id'], now(), decision, triage, form.get('clinical_notes') or None,
                               message, int(referral), destination, reason, followup)).lastrowid
        for name, certainty, is_primary, medication, dosage, instructions in diagnoses:
            diagnosis_id = db.execute('INSERT INTO Diagnosis(case_id,review_id,diagnosis_name,certainty,is_primary) VALUES(?,?,?,?,?)',
                                      (case_id, review_id, name, certainty, is_primary)).lastrowid
            if instructions:
                db.execute('INSERT INTO TreatmentPlan(diagnosis_id,medication,dosage,instructions) VALUES(?,?,?,?)',
                           (diagnosis_id, medication, dosage, instructions))
        db.execute('UPDATE DermCase SET status=? WHERE case_id=?',
                   ('needs_information' if decision == 'needs_information' else 'reviewed', case_id))
        return review_id


def build_analysis_input(case_id, identity):
    role(identity, 'provider')
    db = get_db()
    case = case_access(case_id, identity, db)
    p = db.execute('SELECT * FROM Patient WHERE patient_id=?', (case['patient_id'],)).fetchone()
    age = None
    if p['date_of_birth']:
        born, today = date.fromisoformat(p['date_of_birth']), datetime.now(timezone.utc).date()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    symptom = db.execute('SELECT * FROM Symptom WHERE case_id=?', (case_id,)).fetchone()
    lesions = []
    for l in db.execute('SELECT l.*,b.site_name FROM Lesion l JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY lesion_id', (case_id,)):
        images = []
        for i in db.execute('SELECT * FROM LesionImage WHERE lesion_id=? ORDER BY image_id', (l['lesion_id'],)):
            path = Path(current_app.config['UPLOAD_DIR']) / i['image_uri']
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != i['content_sha256']:
                raise Problem('storage', 409)
            images.append(ImageInput(i['image_id'], i['image_uri'], i['content_sha256'], i['mime_type'], i['image_quality']))
        lesions.append(LesionInput(l['lesion_id'], l['site_name'], tuple(images)))
    return AnalysisInput('1.0', case_id, case['chief_complaint'], case['duration_days'], age, p['sex'],
                         {k: symptom[k] if symptom else None for k in (*SYMPTOMS, 'additional_notes')},
                         tuple(lesions), case['submitted_at'])
