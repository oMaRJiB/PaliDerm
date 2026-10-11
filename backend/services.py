"""CaseWorkflow owns clinical reads/writes, access checks and transactions."""
from contextlib import nullcontext
from datetime import date, datetime, timezone
import json
from flask import current_app
from backend.db import get_db, transaction
from backend.validation import Problem, now, required, calendar, integer, choice, role, contact
from backend.images import ImageStorage
from backend.security import cipher, encrypt_text, reveal
from backend.preprocessing import normalize_gender, symptom_answers, SCINQuestionnaire
from backend.ai.adapter import AnalysisInput, ImageInput, LesionInput

SYMPTOMS = ('itching', 'pain', 'bleeding', 'discharge', 'fever', 'rapidly_worsening')
STATUSES = ('draft', 'submitted', 'in_review', 'needs_information', 'reviewed', 'closed')
DECISIONS = ('confirmed', 'modified', 'needs_information', 'referred', 'inconclusive')
TRIAGE = ('red', 'amber', 'green', 'undetermined')
CONSENT_VERSION = 'local-demo-v1'


def create_patient(form, db=None):
    """Trusted internal profile creation; signup supplies its existing transaction."""
    values = [required(form.get('first_name')), required(form.get('last_name')),
              calendar(form.get('date_of_birth'), birth=True)]
    values += [normalize_gender(form.get('sex')), contact(form.get('phone'), 'phone'), contact(form.get('email'), 'email')]
    values = [encrypt_text('Patient', key, value) for key, value in
              zip(('first_name','last_name','date_of_birth','sex','phone','email'), values)]
    def insert(connection):
        """Use the caller’s transaction so signup cannot leave an orphaned encrypted profile."""
        return connection.execute('INSERT INTO Patient(first_name,last_name,date_of_birth,sex,phone,email) '
                                  'VALUES(?,?,?,?,?,?)', values).lastrowid
    if db is not None:
        return insert(db)
    with transaction() as connection:
        return insert(connection)


class CaseWorkflow:
    """Coordinate authorized clinical operations, encrypted persistence and legal case states."""
    def __init__(self, identity):
        """Bind the current request identity and the startup-validated cipher to private image storage."""
        self.identity = identity
        self.images = ImageStorage(current_app.config, cipher())

    def patient_access(self, patient_id, db=None):
        """Authorize ownership before decrypting and returning a patient row; raise Problem on denial."""
        db = db or get_db()
        row = db.execute('SELECT * FROM Patient WHERE patient_id=?', (patient_id,)).fetchone()
        if not row:
            raise Problem('not_found', 404)
        if not self.identity or self.identity['role'] != 'patient' or self.identity['id'] != patient_id:
            raise Problem('forbidden', 403)
        return reveal('Patient', row)

    def case_access(self, case_id, db=None):
        """Authorize using nonsecret role/link/state metadata before decrypting the case."""
        db = db or get_db()
        row = db.execute('SELECT * FROM DermCase WHERE case_id=?', (case_id,)).fetchone()
        if not row:
            raise Problem('not_found', 404)
        if self.identity and self.identity['role'] == 'patient' and self.identity['id'] == row['patient_id']:
            return reveal('DermCase', row)
        if self.identity and self.identity['role'] == 'provider' and row['status'] != 'draft' and (
            row['provider_id'] is None or row['provider_id'] == self.identity['id']
        ):
            return reveal('DermCase', row)
        raise Problem('forbidden', 403)

    def draft_access(self, case_id, db):
        """Require the owning patient and draft state before allowing an intake mutation."""
        role(self.identity, 'patient')
        row = self.case_access(case_id, db)
        if row['status'] != 'draft':
            raise Problem('transition', 409)
        return row

    def create_case(self, patient_id, form):
        """Validate complaint/duration, persist an encrypted draft and return its case ID."""
        complaint = required(form.get('chief_complaint'))
        duration = integer(form.get('duration_days'))
        with transaction() as db:
            self.patient_access(patient_id, db)
            return db.execute('INSERT INTO DermCase(patient_id,chief_complaint,encrypted_duration) VALUES(?,?,?)',
                              (patient_id, encrypt_text('DermCase','chief_complaint',complaint),
                               cipher().encrypt(duration, 'DermCase.duration_days'))).lastrowid

    def save_draft(self, case_id, form, db=None):
        """Validate then encrypt questionnaire/sites; optional db joins an outer atomic intake transaction."""
        complaint = required(form.get('chief_complaint'))
        try:
            sites = {int(x) for x in form.getlist('body_sites')}
        except (ValueError, TypeError):
            raise Problem('invalid_choice') from None
        with (transaction() if db is None else nullcontext(db)) as db:
            case = self.draft_access(case_id, db)
            # Range answers have no honest exact-day conversion. Preserve legacy
            # numeric durations unless a legacy client explicitly changes them.
            duration = integer(form.get('duration_days')) if 'duration_days' in form else case['duration_days']
            patient = self.patient_access(case['patient_id'], db)
            previous = reveal('Symptom', db.execute('SELECT * FROM Symptom WHERE case_id=?', (case_id,)).fetchone())
            symptoms = symptom_answers(form, previous)
            extras = SCINQuestionnaire().patient_answers(
                form, patient, symptoms, (previous or {}).get('model_metadata'),
                datetime.now(timezone.utc).date())
            if form.get('model_questionnaire_version') == '1' and extras.get('condition_duration'):
                # An explicitly edited range replaces draft numeric duration; do
                # not fabricate an exact day count from a broad training category.
                duration = None
            if extras:
                symptoms['model_metadata'] = extras
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
            db.execute('UPDATE DermCase SET chief_complaint=?,duration_days=NULL,encrypted_duration=? WHERE case_id=?',
                       (encrypt_text('DermCase','chief_complaint',complaint),
                        cipher().encrypt(duration, 'DermCase.duration_days'), case_id))
            # Numeric CHECK constraints remain intact; encrypted answers preserve NULL vs No.
            db.execute('INSERT INTO Symptom(case_id,encrypted_answers,additional_notes) VALUES(?,?,?) '
                       'ON CONFLICT(case_id) DO UPDATE SET encrypted_answers=excluded.encrypted_answers,'
                       'itching=NULL,pain=NULL,bleeding=NULL,discharge=NULL,fever=NULL,rapidly_worsening=NULL,'
                       'additional_notes=excluded.additional_notes',
                       (case_id, cipher().encrypt(symptoms, 'Symptom.answers'),
                        encrypt_text('Symptom','additional_notes',form.get('additional_notes') or None)))


    def upload_images(self, case_id, lesion_id, uploads, db=None):
        """Persist encrypted files/metadata and return storage IDs; clean up new files on any failure."""
        stored_ids = []
        try:
            with (transaction() if db is None else nullcontext(db)) as db:
                self.draft_access(case_id, db)
                if not db.execute('SELECT 1 FROM Lesion WHERE lesion_id=? AND case_id=?', (lesion_id, case_id)).fetchone():
                    raise Problem('invalid_choice')
                uploads = [u for u in uploads if u.filename]
                if not uploads:
                    raise Problem('bad_image')
                count = db.execute('SELECT count(*) FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE l.case_id=?',
                                   (case_id,)).fetchone()[0]
                if count + len(uploads) > self.images.max_count:
                    raise Problem('image_count')
                for upload in uploads:
                    stored = self.images.save(upload)
                    stored_ids.append(stored['image_uri'])
                    db.execute('INSERT INTO LesionImage(lesion_id,image_uri,mime_type,content_sha256) VALUES(?,?,?,?)',
                               (lesion_id, stored['image_uri'], stored['mime_type'], stored['content_sha256']))
        except BaseException:
            for storage_id in stored_ids:
                self.images.discard(storage_id)
            raise
        return stored_ids

    def save_intake(self, case_id, form, uploads):
        """Save questionnaire, new photos and optional consent as one transaction."""
        stored = []
        action = choice(form.get('intake_action', 'save'), ('save', 'submit'))
        try:
            with transaction() as db:
                case = self.case_access(case_id, db)
                role(self.identity, 'patient')
                if case['status'] != 'draft':
                    if action == 'submit' and case['submitted_at']:
                        return True
                    raise Problem('transition', 409)
                self.save_draft(case_id, form, db)
                uploads = [u for u in uploads if u.filename]
                if uploads:
                    site = integer(form.get('photo_body_site'))
                    lesion = db.execute('SELECT lesion_id FROM Lesion WHERE case_id=? AND body_site_id=?',
                                        (case_id, site)).fetchone()
                    if not lesion:
                        raise Problem('photo_site')
                    stored = self.upload_images(case_id, lesion[0], uploads, db)
                if action == 'submit':
                    self.submit_case(case_id, form, db)
            return action == 'submit'
        except BaseException:
            for storage_id in stored:
                self.images.discard(storage_id)
            raise

    def submit_case(self, case_id, form, db=None):
        """Validate saved intake/consent and freeze status/timestamps; retries return False without rewriting."""
        with (transaction() if db is None else nullcontext(db)) as db:
            role(self.identity, 'patient')
            row = self.case_access(case_id, db)
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
                self.images.verify(image)
            stamp = now()
            db.execute("UPDATE DermCase SET status='submitted',submitted_at=?,consent_at=?,consent_version=? WHERE case_id=?",
                       (stamp, stamp, CONSENT_VERSION, case_id))
            return True

    def transition(self, case_id, action):
        """Apply an assigned clinician legal transition; reject invalid state or missing committed review."""
        role(self.identity, 'provider')
        with transaction() as db:
            row = self.case_access(case_id, db)
            targets = {'claim': ('submitted', 'in_review'), 'revise': ('reviewed', 'in_review'), 'close': ('reviewed', 'closed')}
            if action not in targets or row['status'] != targets[action][0]:
                raise Problem('transition', 409)
            if action != 'claim' and row['provider_id'] != self.identity['id']:
                raise Problem('forbidden', 403)
            if action in ('revise', 'close') and not db.execute('SELECT 1 FROM ProviderReview WHERE case_id=?', (case_id,)).fetchone():
                raise Problem('transition', 409)
            db.execute('UPDATE DermCase SET status=?,provider_id=? WHERE case_id=?',
                       (targets[action][1], self.identity['id'], case_id))

    def publish_review(self, case_id, form):
        """Validate plaintext decisions first, then atomically encrypt/save released care and update status."""
        role(self.identity, 'provider')
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
            row = self.case_access(case_id, db)
            if row['provider_id'] != self.identity['id']:
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
                                  (case_id, self.identity['id'], now(), decision, triage,
                                   encrypt_text('ProviderReview','clinical_notes',form.get('clinical_notes') or None),
                                   encrypt_text('ProviderReview','patient_message',message), int(referral),
                                   encrypt_text('ProviderReview','referral_destination',destination),
                                   encrypt_text('ProviderReview','referral_reason',reason),
                                   encrypt_text('ProviderReview','followup_date',followup))).lastrowid
            for name, certainty, is_primary, medication, dosage, instructions in diagnoses:
                diagnosis_id = db.execute('INSERT INTO Diagnosis(case_id,review_id,diagnosis_name,certainty,is_primary) VALUES(?,?,?,?,?)',
                                          (case_id, review_id, encrypt_text('Diagnosis','diagnosis_name',name), certainty, is_primary)).lastrowid
                if instructions:
                    db.execute('INSERT INTO TreatmentPlan(diagnosis_id,medication,dosage,instructions) VALUES(?,?,?,?)',
                               (diagnosis_id, encrypt_text('TreatmentPlan','medication',medication),
                                encrypt_text('TreatmentPlan','dosage',dosage), encrypt_text('TreatmentPlan','instructions',instructions)))
            db.execute('UPDATE DermCase SET status=? WHERE case_id=?',
                       ('needs_information' if decision == 'needs_information' else 'reviewed', case_id))
            return review_id

    def build_analysis_input(self, case_id):
        """Build typed input from authorized recorded answers/profile and verified original image hashes."""
        role(self.identity, 'provider')
        db = get_db()
        case = self.case_access(case_id, db)
        p = reveal('Patient', db.execute('SELECT * FROM Patient WHERE patient_id=?', (case['patient_id'],)).fetchone())
        age = None
        reference = date.fromisoformat(case['submitted_at'][:10]) if case['submitted_at'] else datetime.now(timezone.utc).date()
        if p['date_of_birth']:
            born, today = date.fromisoformat(p['date_of_birth']), reference
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        symptom = reveal('Symptom', db.execute('SELECT * FROM Symptom WHERE case_id=?', (case_id,)).fetchone())
        lesions = []
        for l in db.execute('SELECT l.*,b.site_name FROM Lesion l JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY lesion_id', (case_id,)):
            images = []
            for i in db.execute('SELECT * FROM LesionImage WHERE lesion_id=? ORDER BY image_id', (l['lesion_id'],)):
                self.images.verify(i)
                images.append(ImageInput(i['image_id'], i['image_uri'], i['content_sha256'], i['mime_type'], i['image_quality']))
            lesions.append(LesionInput(l['lesion_id'], l['site_name'], tuple(images)))
        return AnalysisInput('1.0', case_id, case['chief_complaint'], case['duration_days'], age, p['sex'],
                             {k: symptom[k] if symptom else None for k in (*SYMPTOMS, 'additional_notes')},
                             tuple(lesions), case['submitted_at'],
                             self.model_answers(p, symptom, reference))

    @staticmethod
    def model_answers(patient, symptom, reference):
        """Merge saved extras/known symptoms with server-derived profile categories.

        Older questionnaires may have no extras. No absent binary answer becomes
        zero, and age uses the submission date so historical inputs do not drift.
        """
        values = dict((symptom or {}).get('model_metadata') or {})
        for name, key in SCINQuestionnaire.SYMPTOM_FIELDS.items():
            values[name] = (symptom or {}).get(key)
        values.update(SCINQuestionnaire.profile_values(patient, reference))
        return values

    def profile(self, patient_id):
        """Return only the owning patient and decrypted case list for presentation."""
        patient = self.patient_access(patient_id)
        cases = get_db().execute('SELECT * FROM DermCase WHERE patient_id=? ORDER BY case_id DESC', (patient_id,)).fetchall()
        return {'patient': patient, 'cases': [reveal('DermCase', row) for row in cases]}

    def new_case_profile(self):
        """Require a patient account and return its own profile for draft creation."""
        role(self.identity, 'patient')
        return self.patient_access(self.identity['id'])

    def image_file(self, image_id):
        """Authorize the parent case before decrypting image bytes; return bytes and recorded MIME."""
        row = get_db().execute('SELECT i.*,l.case_id FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE image_id=?', (image_id,)).fetchone()
        if not row:
            raise Problem('not_found', 404)
        self.case_access(row['case_id'])
        return self.images.read_original(row['image_uri'], row['content_sha256']), row['mime_type']

    def case_details(self, case_id):
        """Return authorized presentation data, withholding private notes and AI history from patients."""
        db = get_db()
        case = self.case_access(case_id)
        patient = reveal('Patient', db.execute('SELECT * FROM Patient WHERE patient_id=?', (case['patient_id'],)).fetchone())
        symptom = reveal('Symptom', db.execute('SELECT * FROM Symptom WHERE case_id=?', (case_id,)).fetchone())
        lesions = db.execute('SELECT l.*,b.site_name FROM Lesion l JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY lesion_id', (case_id,)).fetchall()
        images = db.execute('SELECT i.*,l.body_site_id,b.site_name FROM LesionImage i JOIN Lesion l USING(lesion_id) '
                            'JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY image_id', (case_id,)).fetchall()
        reviews = db.execute('SELECT r.*,p.name FROM ProviderReview r JOIN Provider p USING(provider_id) '
                             'WHERE case_id=? ORDER BY reviewed_at DESC,review_id DESC', (case_id,)).fetchall()
        provider_view = self.identity['role'] == 'provider'
        if not provider_view:
            # Patients receive released care only, never private notes even in service data.
            reviews = [{key: row[key] for key in row.keys() if key != 'clinical_notes'} for row in reviews]
        reviews = [reveal('ProviderReview', row) for row in reviews]
        latest = reviews[0] if reviews else None
        diagnoses = db.execute('SELECT * FROM Diagnosis WHERE review_id=? ORDER BY is_primary DESC,diagnosis_id', (latest['review_id'],)).fetchall() if latest else []
        treatments = db.execute('SELECT t.*,d.diagnosis_name FROM TreatmentPlan t JOIN Diagnosis d USING(diagnosis_id) WHERE d.review_id=?', (latest['review_id'],)).fetchall() if latest else []
        diagnoses = [reveal('Diagnosis', row) for row in diagnoses]
        treatments = [reveal('TreatmentPlan', reveal('Diagnosis', row)) for row in treatments]
        analyses = db.execute('SELECT * FROM AIAnalysis WHERE case_id=? ORDER BY analysis_id DESC', (case_id,)).fetchall() if provider_view else []
        analyses = [reveal('AIAnalysis', row) for row in analyses]
        for analysis in analyses:
            # Legacy plain narrative strings remain unchanged. Decode only our
            # encrypted versioned output envelope, never the submitted snapshot.
            try:
                envelope = json.loads(analysis['rationale'] or '')
            except (ValueError, TypeError):
                continue
            if isinstance(envelope, dict) and envelope.get('format') == 'paliderm-triage-v1':
                analysis['rationale'] = envelope['rationale']
                analysis['assisted_triage'] = envelope['triage']
        latest_success = next((a for a in analyses if a['status'] == 'completed'), None)
        candidates = db.execute('SELECT * FROM AICandidate WHERE analysis_id=? ORDER BY rank', (latest_success['analysis_id'],)).fetchall() if latest_success else []
        candidates = [reveal('AICandidate', row) for row in candidates]
        reference = date.fromisoformat(case['submitted_at'][:10]) if case['submitted_at'] else datetime.now(timezone.utc).date()
        model_answers = self.model_answers(patient, symptom, reference)
        return {'case': case,
                'patient': patient,
                'symptom': symptom,
                'symptoms_complete': bool(symptom) and all(symptom.get(key) in (0, 1) for key in SYMPTOMS),
                'model_answers': model_answers,
                'patient_model_groups': SCINQuestionnaire().fields(model_answers, patient=True),
                'lesions': lesions,
                'images': images,
                'sites': db.execute('SELECT * FROM BodySite ORDER BY body_site_id').fetchall(),
                'selected_sites': {l['body_site_id'] for l in lesions},
                'latest': latest,
                'reviews': reviews if provider_view else [],
                'diagnoses': diagnoses,
                'treatments': treatments,
                'analyses': analyses,
                'latest_success': latest_success,
                'candidates': candidates,
                'review_base': max([r['review_id'] for r in reviews], default=0)}

    def queue(self, filters):
        """Filter by state/reviewer and assignment before decrypting patient names for clinicians."""
        role(self.identity, 'provider')
        status = filters.get('status', '')
        reviewer = filters.get('reviewer', '')
        if status and status not in STATUSES[1:]:
            raise Problem('invalid_choice')
        db = get_db()
        providers = db.execute('SELECT * FROM Provider ORDER BY provider_id').fetchall()
        if reviewer and reviewer not in {'unassigned', *[str(p['provider_id']) for p in providers]}:
            raise Problem('invalid_choice')
        # Other clinicians' assigned records do not appear in this identity's queue.
        sql = "SELECT c.*,p.first_name,p.last_name,v.name,r.triage_level,a.triage_level AS ai_triage FROM DermCase c JOIN Patient p USING(patient_id) " \
              "LEFT JOIN Provider v USING(provider_id) LEFT JOIN ProviderReview r ON r.review_id=(SELECT rr.review_id FROM ProviderReview rr " \
              "WHERE rr.case_id=c.case_id ORDER BY rr.reviewed_at DESC,rr.review_id DESC LIMIT 1) " \
              "LEFT JOIN AIAnalysis a ON a.analysis_id=(SELECT aa.analysis_id FROM AIAnalysis aa WHERE aa.case_id=c.case_id AND aa.status='completed' ORDER BY aa.analysis_id DESC LIMIT 1) " \
              "WHERE c.status!='draft' AND (c.provider_id IS NULL OR c.provider_id=?)"
        params = [self.identity['id']]
        if status:
            sql += ' AND c.status=?'
            params.append(status)
        else:
            sql += " AND c.status IN ('submitted','in_review','needs_information')"
        if reviewer == 'unassigned':
            sql += ' AND c.provider_id IS NULL'
        elif reviewer:
            sql += ' AND c.provider_id=?'
            params.append(int(reviewer))
        rows = db.execute(sql + ' ORDER BY c.submitted_at,c.case_id', params).fetchall()
        rows = [reveal('DermCase', reveal('Patient', row)) for row in rows]
        ages = {r['case_id']: round((datetime.now(timezone.utc)-datetime.fromisoformat(r['submitted_at'].replace('Z', '+00:00'))).total_seconds()/3600, 1) for r in rows}
        return {'cases':rows,'providers':providers,'selected_status':status,'selected_reviewer':reviewer,'ages':ages}
