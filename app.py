"""Local-only Flask/Jinja prototype. Run using `flask --app app run --host 127.0.0.1`."""
import hmac
import os
import secrets
import sqlite3
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path
import click
from flask import Flask, g, redirect, render_template, request, send_file, session, url_for, flash
from werkzeug.exceptions import HTTPException
from backend.db import ROOT, close_db, get_db, initialize
from backend.i18n import translate
from backend import services as svc
from backend.ai.adapter import UnconfiguredAdapter, AIUnavailable
from backend.ai.runner import run_analysis, recover_interrupted


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get('DATABASE', str(ROOT / 'instance/demo.sqlite3')),
        UPLOAD_DIR=os.environ.get('UPLOAD_DIR', str(ROOT / 'instance/uploads')),
        APP_LOCALE=os.environ.get('APP_LOCALE', 'en'),
        MAX_IMAGE_BYTES=int(os.environ.get('MAX_IMAGE_BYTES', 8 * 1024 * 1024)),
        MAX_IMAGE_COUNT=int(os.environ.get('MAX_IMAGE_COUNT', 12)),
        MAX_IMAGE_PIXELS=int(os.environ.get('MAX_IMAGE_PIXELS', 20_000_000)),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        AI_ADAPTER=UnconfiguredAdapter(), AI_TIMEOUT_SECONDS=15,
    )
    if config:
        app.config.update(config)
    for key in ('DATABASE', 'UPLOAD_DIR'):
        app.config[key] = str((ROOT / app.config[key]).resolve())
    app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_IMAGE_BYTES'] * app.config['MAX_IMAGE_COUNT'] + 1024 * 1024
    Path(app.config['UPLOAD_DIR']).mkdir(parents=True, exist_ok=True)
    initialize(app.config['DATABASE'])
    recover_interrupted(app.config['DATABASE'])
    secret = app.config.get('SECRET_KEY') or os.environ.get('SECRET_KEY')
    if not secret:
        keypath = ROOT / 'instance/session.key'
        keypath.parent.mkdir(parents=True, exist_ok=True)
        try:
            with keypath.open('x', encoding='utf-8') as f:
                os.chmod(keypath, 0o600)
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass
        secret = keypath.read_text(encoding='utf-8')
    app.secret_key = secret
    app.teardown_appcontext(close_db)

    def t(key, **values):
        return translate(key, g.get('locale', 'en'), **values)

    @app.before_request
    def local_and_session():
        host = urlsplit('http://' + request.host).hostname
        if request.remote_addr not in ('127.0.0.1', '::1') or host not in ('localhost', '127.0.0.1', '::1'):
            raise svc.Problem('local_only', 403)
        g.locale = app.config['APP_LOCALE'] if app.config['APP_LOCALE'] in ('en', 'ar') else 'en'
        g.identity = None
        token = session.get('identity', '')
        if token == 'worker-demo':
            g.identity = {'role': 'worker', 'id': None, 'name': t('worker')}
        elif isinstance(token, str) and ':' in token:
            role, ident = token.split(':', 1)
            if role in ('patient', 'provider') and ident.isascii() and ident.isdigit():
                table, key = ('Patient', 'patient_id') if role == 'patient' else ('Provider', 'provider_id')
                row = get_db().execute(f'SELECT * FROM {table} WHERE {key}=?', (int(ident),)).fetchone()
                if row:
                    name = row['first_name'] + ' ' + row['last_name'] if role == 'patient' else row['name']
                    g.identity = {'role': role, 'id': int(ident), 'name': name}
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and not hmac.compare_digest(session['csrf'], request.form.get('csrf', '')):
            raise svc.Problem('csrf', 400)

    @app.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
        return response

    @app.context_processor
    def context():
        return {'t': t, 'locale': g.get('locale', 'en'), 'direction': 'rtl' if g.get('locale') == 'ar' else 'ltr',
                'identity': g.get('identity'), 'csrf': session.get('csrf'), 'symptom_keys': svc.SYMPTOMS,
                'statuses': svc.STATUSES, 'decisions': svc.DECISIONS, 'triage_options': svc.TRIAGE}

    @app.errorhandler(svc.Problem)
    def problem(error):
        return render_template('error.html', error_key=error.key), error.status

    @app.errorhandler(sqlite3.Error)
    @app.errorhandler(OSError)
    def storage_error(error):
        # Do not log intake, images, SQL parameters or exception contents.
        return render_template('error.html', error_key='storage'), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        key = {404: 'not_found', 413: 'too_large', 403: 'forbidden'}.get(error.code, 'error')
        return render_template('error.html', error_key=key), error.code

    @app.route('/')
    def home():
        if g.identity and g.identity['role'] == 'patient':
            return redirect(url_for('profile', patient_id=g.identity['id']))
        if g.identity and g.identity['role'] == 'provider':
            return redirect(url_for('queue'))
        return render_template('home.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        db = get_db()
        patients = db.execute('SELECT * FROM Patient ORDER BY patient_id').fetchall()
        providers = db.execute('SELECT * FROM Provider ORDER BY provider_id').fetchall()
        identities = {'worker-demo'} | {f'patient:{p["patient_id"]}' for p in patients} | {f'provider:{p["provider_id"]}' for p in providers}
        if request.method == 'POST':
            if request.form.get('identity') not in identities:
                raise svc.Problem('invalid_choice')
            identity_token = request.form['identity']
            session.clear()
            session['identity'] = identity_token
            session['csrf'] = secrets.token_hex(32)
            return redirect(url_for('home'))
        return render_template('login.html', patients=patients, providers=providers)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.route('/patients/new', methods=['GET', 'POST'])
    def register():
        if g.identity and g.identity['role'] != 'patient':
            raise svc.Problem('forbidden', 403)
        if request.method == 'POST':
            patient_id = svc.create_patient(request.form)
            session['identity'] = f'patient:{patient_id}'
            return redirect(url_for('profile', patient_id=patient_id))
        return render_template('register.html')

    @app.get('/patients/<int:patient_id>')
    def profile(patient_id):
        patient = svc.patient_access(patient_id, g.identity)
        cases = get_db().execute('SELECT * FROM DermCase WHERE patient_id=? ORDER BY case_id DESC', (patient_id,)).fetchall()
        return render_template('profile.html', patient=patient, cases=cases)

    @app.post('/patients/<int:patient_id>/cases')
    def new_case(patient_id):
        case_id = svc.create_case(patient_id, request.form, g.identity)
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/cases/<int:case_id>')
    def case_page(case_id):
        db = get_db()
        case = svc.case_access(case_id, g.identity)
        patient = db.execute('SELECT * FROM Patient WHERE patient_id=?', (case['patient_id'],)).fetchone()
        symptom = db.execute('SELECT * FROM Symptom WHERE case_id=?', (case_id,)).fetchone()
        lesions = db.execute('SELECT l.*,b.site_name FROM Lesion l JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY lesion_id', (case_id,)).fetchall()
        images = db.execute('SELECT i.*,l.body_site_id,b.site_name FROM LesionImage i JOIN Lesion l USING(lesion_id) '
                            'JOIN BodySite b USING(body_site_id) WHERE case_id=? ORDER BY image_id', (case_id,)).fetchall()
        reviews = db.execute('SELECT r.*,p.name FROM ProviderReview r JOIN Provider p USING(provider_id) '
                             'WHERE case_id=? ORDER BY reviewed_at DESC,review_id DESC', (case_id,)).fetchall()
        latest = reviews[0] if reviews else None
        diagnoses = db.execute('SELECT * FROM Diagnosis WHERE review_id=? ORDER BY is_primary DESC,diagnosis_id', (latest['review_id'],)).fetchall() if latest else []
        treatments = db.execute('SELECT t.*,d.diagnosis_name FROM TreatmentPlan t JOIN Diagnosis d USING(diagnosis_id) WHERE d.review_id=?', (latest['review_id'],)).fetchall() if latest else []
        analyses = db.execute('SELECT * FROM AIAnalysis WHERE case_id=? ORDER BY analysis_id DESC', (case_id,)).fetchall()
        latest_success = next((a for a in analyses if a['status'] == 'completed'), None)
        candidates = db.execute('SELECT * FROM AICandidate WHERE analysis_id=? ORDER BY rank', (latest_success['analysis_id'],)).fetchall() if latest_success else []
        return render_template('case.html', case=case, patient=patient, symptom=symptom, lesions=lesions, images=images,
                               sites=db.execute('SELECT * FROM BodySite ORDER BY body_site_id').fetchall(),
                               selected_sites={l['body_site_id'] for l in lesions}, latest=latest, reviews=reviews,
                               diagnoses=diagnoses, treatments=treatments, analyses=analyses, latest_success=latest_success,
                               candidates=candidates, review_base=max([r['review_id'] for r in reviews], default=0),
                               ai_configured=not isinstance(app.config['AI_ADAPTER'], UnconfiguredAdapter),
                               image_help=t('image_help', count=app.config['MAX_IMAGE_COUNT'], mb=app.config['MAX_IMAGE_BYTES']//1024//1024,
                                            pixels=app.config['MAX_IMAGE_PIXELS']))

    @app.post('/cases/<int:case_id>/draft')
    def save_draft(case_id):
        svc.save_draft(case_id, request.form, g.identity)
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/images')
    def upload(case_id):
        try:
            lesion_id = int(request.form.get('lesion_id', ''))
        except ValueError:
            raise svc.Problem('invalid_choice') from None
        svc.upload_images(case_id, lesion_id, request.files.getlist('images'), g.identity)
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/images/<int:image_id>')
    def image(image_id):
        row = get_db().execute('SELECT i.*,l.case_id FROM LesionImage i JOIN Lesion l USING(lesion_id) WHERE image_id=?', (image_id,)).fetchone()
        if not row:
            raise svc.Problem('not_found', 404)
        svc.case_access(row['case_id'], g.identity)
        # Client receives only an integer identifier; stored file names must match generated IDs.
        import re
        if not re.fullmatch(r'[a-f0-9]{32}\.png', row['image_uri']):
            raise svc.Problem('not_found', 404)
        path = Path(app.config['UPLOAD_DIR']) / row['image_uri']
        if not path.is_file():
            raise svc.Problem('not_found', 404)
        return send_file(path, mimetype=row['mime_type'], conditional=False)

    @app.post('/cases/<int:case_id>/submit')
    def submit(case_id):
        svc.submit_case(case_id, request.form, g.identity)
        flash(t('submitted_notice'))
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/queue')
    def queue():
        svc.role(g.identity, 'provider')
        status = request.args.get('status', '')
        reviewer = request.args.get('reviewer', '')
        if status and status not in svc.STATUSES[1:]:
            raise svc.Problem('invalid_choice')
        db = get_db()
        providers = db.execute('SELECT * FROM Provider ORDER BY provider_id').fetchall()
        if reviewer and reviewer not in {'unassigned', *[str(p['provider_id']) for p in providers]}:
            raise svc.Problem('invalid_choice')
        # Other clinicians' assigned records do not appear in this identity's queue.
        sql = "SELECT c.*,p.first_name,p.last_name,v.name,r.triage_level,a.triage_level AS ai_triage FROM DermCase c JOIN Patient p USING(patient_id) " \
              "LEFT JOIN Provider v USING(provider_id) LEFT JOIN ProviderReview r ON r.review_id=(SELECT rr.review_id FROM ProviderReview rr " \
              "WHERE rr.case_id=c.case_id ORDER BY rr.reviewed_at DESC,rr.review_id DESC LIMIT 1) " \
              "LEFT JOIN AIAnalysis a ON a.analysis_id=(SELECT aa.analysis_id FROM AIAnalysis aa WHERE aa.case_id=c.case_id AND aa.status='completed' ORDER BY aa.analysis_id DESC LIMIT 1) " \
              "WHERE c.status!='draft' AND (c.provider_id IS NULL OR c.provider_id=?)"
        params = [g.identity['id']]
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
        ages = {r['case_id']: round((datetime.now(timezone.utc)-datetime.fromisoformat(r['submitted_at'].replace('Z', '+00:00'))).total_seconds()/3600, 1) for r in rows}
        return render_template('queue.html', cases=rows, providers=providers, selected_status=status, selected_reviewer=reviewer, ages=ages)

    @app.post('/cases/<int:case_id>/transition')
    def transition(case_id):
        svc.transition(case_id, request.form.get('action'), g.identity)
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/review')
    def review(case_id):
        svc.publish_review(case_id, request.form, g.identity)
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/analyze')
    def analyze(case_id):
        svc.role(g.identity, 'provider')
        svc.case_access(case_id, g.identity)
        try:
            base = request.form.get('analysis_base', '0')
            if not base.isascii() or not base.isdigit():
                raise svc.Problem('invalid_choice')
            run_analysis(case_id, g.identity, app.config['AI_ADAPTER'], base, app.config['AI_TIMEOUT_SECONDS'])
        except AIUnavailable:
            raise svc.Problem('ai_pending', 503) from None
        return redirect(url_for('case_page', case_id=case_id))

    @app.cli.command('init-db')
    def init_db():
        """Check/initialize a separate runtime v2 database without resetting it."""
        click.echo(f'Initialized/verified v2: {app.config["DATABASE"]}')

    @app.cli.command('seed-demo')
    def seed_demo():
        """Seed synthetic records only in the named demo.sqlite3 database."""
        from backend.demo import seed
        seed(app)
        click.echo('Synthetic demo records ready. Identities: patient:1, patient:2, provider:1, provider:2, worker-demo.')

    @app.cli.command('reset-demo')
    @click.option('--confirm-demo', is_flag=True, required=True, help='Explicitly reset only demo.sqlite3.')
    def reset_demo(confirm_demo):
        """Reset/seed only the named demo database; keep all unreferenced image files."""
        from backend.demo import reset
        reset(app)
        click.echo('Reset and seeded the named demo database. Unreferenced files retained; no directory was deleted.')

    return app
