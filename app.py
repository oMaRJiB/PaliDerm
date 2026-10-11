"""Local-only Flask/Jinja prototype. Run using `flask --app app run --host 127.0.0.1`."""
import io
import hmac
import os
import secrets
import sqlite3
from urllib.parse import urlsplit
from pathlib import Path
import click
from flask import Flask, g, redirect, render_template, request, send_file, session, url_for, flash, jsonify
from werkzeug.exceptions import HTTPException
from backend.db import ROOT, close_db, initialize
from backend.i18n import translate, brief_triage_reason
from backend import services as svc
from backend.auth import AuthService
from backend.security import Cipher, EncryptionError
from backend.ai.adapter import UnconfiguredAdapter, AIUnavailable
from backend.ai.runner import run_analysis, recover_interrupted


def create_app(config=None):
    """Configure a loopback-only encrypted Flask application; fail before serving on invalid key/schema."""
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE=os.environ.get('DATABASE', str(ROOT / 'instance/encrypted/demo.sqlite3')),
        UPLOAD_DIR=os.environ.get('UPLOAD_DIR', str(ROOT / 'instance/encrypted/uploads')),
        APP_LOCALE=os.environ.get('APP_LOCALE', 'en'),
        ENCRYPTION_KEY=os.environ.get('ENCRYPTION_KEY'),
        # Direct CLI commands share the launcher's existing local key. Never
        # generate a replacement or override an explicitly supplied key source.
        ENCRYPTION_KEY_FILE=os.environ.get('ENCRYPTION_KEY_FILE',
            None if os.environ.get('ENCRYPTION_KEY') else str(ROOT / 'instance/encryption.key')),
        # Omar selected this saved bundle; an explicitly empty value disables AI.
        MODEL_PATH=os.environ.get('MODEL_PATH', str(ROOT / 'notebooks/SCIN_custom_model.keras')),
        SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0') == '1',
        MAX_IMAGE_BYTES=int(os.environ.get('MAX_IMAGE_BYTES', 8 * 1024 * 1024)),
        MAX_IMAGE_COUNT=int(os.environ.get('MAX_IMAGE_COUNT', 12)),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
        AI_ADAPTER=UnconfiguredAdapter(), AI_TIMEOUT_SECONDS=float(os.environ.get('AI_TIMEOUT_SECONDS', 60)),
        AI_TRIAGE_DEMO_THRESHOLD=float(os.environ.get('AI_TRIAGE_DEMO_THRESHOLD', '0.5')),
    )
    if config:
        app.config.update(config)
        if config.get('ENCRYPTION_KEY') and 'ENCRYPTION_KEY_FILE' not in config and 'ENCRYPTION_KEY_FILE' not in os.environ:
            app.config['ENCRYPTION_KEY_FILE'] = None
    for key in ('DATABASE', 'UPLOAD_DIR'):
        app.config[key] = str((ROOT / app.config[key]).resolve())
    if app.config['ENCRYPTION_KEY_FILE']:
        app.config['ENCRYPTION_KEY_FILE'] = str((ROOT / app.config['ENCRYPTION_KEY_FILE']).resolve())
    for private in ('DATABASE', 'UPLOAD_DIR', 'ENCRYPTION_KEY_FILE'):
        if app.config.get(private) and Path(app.config[private]).is_relative_to(Path(app.static_folder).resolve()):
            raise RuntimeError(f'{private} must be outside public static assets.')
    # Changing the default must not hide unmigrated records behind a new empty DB.
    default_database = ROOT / 'instance/encrypted/demo.sqlite3'
    if (Path(app.config['DATABASE']) == default_database.resolve()
            and not default_database.exists() and (ROOT / 'instance/demo.sqlite3').exists()):
        raise RuntimeError('A legacy database exists but its encrypted copy is missing. Stop the server and run '
                           'python -m backend.migrate_encryption --source-db instance/demo.sqlite3 '
                           '--source-uploads instance/uploads --destination instance/encrypted '
                           'with the encryption key configured. No empty replacement database was created.')
    app.extensions['cipher'] = Cipher.from_config(app.config)
    app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_IMAGE_BYTES'] * app.config['MAX_IMAGE_COUNT'] + 1024 * 1024
    Path(app.config['UPLOAD_DIR']).mkdir(parents=True, exist_ok=True, mode=0o700)
    initialize(app.config['DATABASE'], app.extensions['cipher'])
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
    auth = AuthService()
    if app.config['MODEL_PATH'] and not (config and 'AI_ADAPTER' in config):
        # Model choice is administrator configuration, never a client path.
        # Framework loading stays lazy and unavailable AI cannot block review.
        from backend.ai.local_adapter import SCINModelAdapter
        from backend.images import ImageStorage
        try:
            app.config['AI_ADAPTER'] = SCINModelAdapter(
                ROOT / app.config['MODEL_PATH'],
                ImageStorage(app.config, app.extensions['cipher']), app.config['APP_LOCALE'],
                triage_threshold=app.config['AI_TRIAGE_DEMO_THRESHOLD'],
            )
        except AIUnavailable:
            app.config['AI_ADAPTER'] = UnconfiguredAdapter('ai_model_unavailable')

    def workflow():
        """Create a service with the identity resolved for this request."""
        return svc.CaseWorkflow(g.identity)

    def t(key, **values):
        """Translate presentation strings using the current request locale."""
        return translate(key, g.get('locale', 'en'), **values)

    @app.template_filter('ai_score')
    def ai_score(value):
        """Display scores as readable percentages without changing saved values.

        Very small/large nonzero scores keep bounds rather than rounding to a
        misleading zero or certainty. The template explains this is match, not risk.
        """
        if value is None:
            return t('ai_score_unknown')
        if 0 < value < 0.01:
            return t('ai_score_small')
        if 0.99 < value < 1:
            return t('ai_score_large')
        percent = min(99, max(1, round(value * 100))) if 0 < value < 1 else round(value * 100)
        return t('ai_score_percent', percent=percent)

    @app.template_filter('brief_triage')
    def brief_triage(reason):
        """Present legacy explanations concisely without modifying encrypted history."""
        return brief_triage_reason(reason, g.get('locale', 'en'))

    @app.before_request
    def local_and_session():
        """Enforce loopback access, reload account authority and validate CSRF before routes."""
        host = urlsplit('http://' + request.host).hostname
        if request.remote_addr not in ('127.0.0.1', '::1') or host not in ('localhost', '127.0.0.1', '::1'):
            raise svc.Problem('local_only', 403)
        g.locale = app.config['APP_LOCALE'] if app.config['APP_LOCALE'] in ('en', 'ar') else 'en'
        g.identity = auth.identity()
        if 'csrf' not in session:
            session['csrf'] = secrets.token_hex(32)
        if request.method == 'POST' and (not request.form.get('csrf', '').isascii()
                or not hmac.compare_digest(session['csrf'], request.form.get('csrf', ''))):
            raise svc.Problem('csrf', 400)

    @app.after_request
    def private_response(response):
        # Enhanced forms navigate only after a committed write. Keep flash notices
        # for the browser's destination GET rather than consuming them in fetch.
        """Preserve confirmed redirects for enhanced forms and apply private-response security headers."""
        if (request.method == 'POST' and response.status_code == 302
                and request.headers.get('X-Form-Response') == 'json'):
            response = jsonify(redirect=response.headers['Location'])
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob:; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
        return response

    @app.context_processor
    def context():
        """Expose translated labels and nonsecret request identity/CSRF to the shared templates."""
        return {'t': t, 'locale': g.get('locale', 'en'), 'direction': 'rtl' if g.get('locale') == 'ar' else 'ltr',
                'identity': g.get('identity'), 'csrf': session.get('csrf'), 'symptom_keys': svc.SYMPTOMS,
                'statuses': svc.STATUSES, 'decisions': svc.DECISIONS, 'triage_options': svc.TRIAGE}

    @app.errorhandler(svc.Problem)
    def problem(error):
        """Render a translated validation/authorization error without logging submitted content."""
        return render_template('error.html', error_key=error.key), error.status

    @app.errorhandler(EncryptionError)
    @app.errorhandler(sqlite3.Error)
    @app.errorhandler(OSError)
    def storage_error(error):
        # Do not log intake, images, SQL parameters or exception contents.
        """Return a generic storage/authentication failure without leaking SQL, keys or clinical values."""
        return render_template('error.html', error_key='storage'), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        """Translate expected HTTP errors while preserving their status code."""
        key = {404: 'not_found', 413: 'too_large', 403: 'forbidden'}.get(error.code, 'error')
        return render_template('error.html', error_key=key), error.code

    @app.route('/')
    def home():
        """Render role-appropriate entry actions without reading other patients’ clinical records."""
        return render_template('home.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Delegate password verification/session rotation and redirect only after success."""
        if request.method == 'POST':
            auth.login(request.form)
            return redirect(url_for('home'))
        return render_template('login.html')

    @app.post('/logout')
    def logout():
        """Clear the account session through a CSRF-protected POST."""
        auth.logout()
        return redirect(url_for('login'))

    @app.route('/patients/new', methods=['GET', 'POST'])
    def register():
        """Delegate patient-only encrypted signup; disallow role/entity self-selection."""
        if g.identity:
            raise svc.Problem('already_signed_in', 403)
        if request.method == 'POST':
            patient_id = auth.signup(request.form)
            return redirect(url_for('profile', patient_id=patient_id))
        return render_template('register.html')

    @app.get('/my-cases')
    def my_cases():
        """Require a patient and redirect to its server-linked profile."""
        svc.role(g.identity, 'patient')
        return redirect(url_for('profile', patient_id=g.identity['id']))

    @app.get('/cases/new')
    def new_case_form():
        """Render the authorized patient draft-creation form."""
        return render_template('new_case.html', patient=workflow().new_case_profile())

    @app.get('/patients/<int:patient_id>')
    def profile(patient_id):
        """Render the owning patient profile and authorized case list."""
        return render_template('profile.html', **workflow().profile(patient_id))

    @app.post('/patients/<int:patient_id>/cases')
    def new_case(patient_id):
        """Create an encrypted draft through the workflow service and return its location."""
        case_id = workflow().create_case(patient_id, request.form)
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/cases/<int:case_id>')
    def case_page(case_id):
        """Render the role-authorized intake or released case outcome."""
        details = workflow().case_details(case_id)
        adapter = app.config['AI_ADAPTER']
        fields = getattr(adapter, 'input_fields', None)
        input_groups = fields(details['symptom'], metadata=details['model_answers']) if fields and g.identity['role'] == 'provider' else []
        return render_template('case.html', **details,
                               ai_input_groups=input_groups,
                               ai_notice_key=getattr(adapter, 'notice_key', 'ai_configured'),
                               ai_configured=not isinstance(app.config['AI_ADAPTER'], UnconfiguredAdapter),
                               image_help=t('image_help', count=app.config['MAX_IMAGE_COUNT'],
                                            mb=app.config['MAX_IMAGE_BYTES']//1024//1024))

    @app.post('/cases/<int:case_id>/intake')
    def save_intake(case_id):
        """Delegate combined questionnaire/camera/file/consent persistence to one transaction."""
        submitted = workflow().save_intake(case_id, request.form,
                                         request.files.getlist('images') + request.files.getlist('camera'))
        flash(t('submitted_notice' if submitted else 'draft_saved'))
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/draft')
    def save_draft(case_id):
        """Delegate a validated draft edit and redirect to the existing case."""
        workflow().save_draft(case_id, request.form)
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/images')
    def upload(case_id):
        """Validate the supplied lesion identifier and delegate authorized encrypted uploads."""
        try:
            lesion_id = int(request.form.get('lesion_id', ''))
        except ValueError:
            raise svc.Problem('invalid_choice') from None
        workflow().upload_images(case_id, lesion_id, request.files.getlist('images'))
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/images/<int:image_id>')
    def image(image_id):
        """Serve authenticated decrypted bytes from memory only after parent-case authorization."""
        data, mime_type = workflow().image_file(image_id)
        return send_file(io.BytesIO(data), mimetype=mime_type, conditional=False)

    @app.post('/cases/<int:case_id>/submit')
    def submit(case_id):
        """Delegate consent validation and show a server-confirmed submission notice."""
        workflow().submit_case(case_id, request.form)
        flash(t('submitted_notice'))
        return redirect(url_for('case_page', case_id=case_id))

    @app.get('/queue')
    def queue():
        """Render the clinician’s authorized queue/filter results."""
        return render_template('queue.html', **workflow().queue(request.args))

    @app.post('/cases/<int:case_id>/transition')
    def transition(case_id):
        """Delegate an explicit legal clinician lifecycle action."""
        workflow().transition(case_id, request.form.get('action'))
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/review')
    def review(case_id):
        """Delegate atomic clinician review publication; AI availability is independent."""
        workflow().publish_review(case_id, request.form)
        return redirect(url_for('case_page', case_id=case_id))

    @app.post('/cases/<int:case_id>/analyze')
    def analyze(case_id):
        """Delegate authorized inference and required inputs through the replaceable adapter boundary."""
        svc.role(g.identity, 'provider')
        try:
            base = request.form.get('analysis_base', '0')
            if not base.isascii() or not base.isdigit():
                raise svc.Problem('invalid_choice')
            run_analysis(case_id, g.identity, app.config['AI_ADAPTER'], base, app.config['AI_TIMEOUT_SECONDS'],
                         supplemental=request.form)
        except AIUnavailable:
            raise svc.Problem(getattr(app.config['AI_ADAPTER'], 'notice_key', 'ai_pending'), 503) from None
        return redirect(url_for('case_page', case_id=case_id))

    @app.cli.command('init-db')
    def init_db():
        """Check/initialize runtime v4 without resetting it."""
        click.echo(f'Initialized/verified v4: {app.config["DATABASE"]}')

    @app.cli.command('seed-demo')
    def seed_demo():
        """Seed synthetic records only in the named demo.sqlite3 database."""
        from backend.demo import seed
        seed(app)
        click.echo('Synthetic records ready. Use provision-account to set private login credentials; no default passwords exist.')

    @app.cli.command('provision-account')
    @click.option('--username', required=True)
    @click.option('--role', 'account_role', type=click.Choice(['patient', 'provider', 'worker']), required=True)
    @click.option('--patient-id', type=int)
    @click.option('--provider-id', type=int)
    @click.password_option(confirmation_prompt=True)
    def provision_account(username, account_role, patient_id, provider_id, password):
        """Create a credentialed account or link an existing patient/provider; no HTTP privilege selection."""
        try:
            account_id = auth.provision(username, password, account_role, patient_id, provider_id)
        except svc.Problem as error:
            raise click.ClickException(translate(error.key)) from None
        click.echo(f'Created account {account_id} ({account_role}); no clinical records were changed.')

    @app.cli.command('reset-demo')
    @click.option('--confirm-demo', is_flag=True, required=True, help='Explicitly reset only demo.sqlite3.')
    @click.option('--purge-images', is_flag=True, help='Also remove old files from the dedicated demo upload directory.')
    @click.option('--create-test-accounts', is_flag=True, help='Create synthetic logins and a private plaintext credential file.')
    def reset_demo(confirm_demo, purge_images, create_test_accounts):
        """Reset the named demo, optionally clearing images and creating test logins."""
        from backend.demo import reset
        reset(app, purge_images=purge_images, create_test_accounts=create_test_accounts)
        click.echo('Reset and seeded demo.sqlite3. Encryption key, source files and models preserved.')
        if create_test_accounts:
            click.echo('Synthetic login credentials: instance/test-accounts.txt (private, plaintext, local demo only).')

    return app
