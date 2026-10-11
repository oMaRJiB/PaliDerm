"""Accounts, password verification and signed-session lifecycle; no selectable roles."""
import re
import secrets
import sqlite3
from flask import session
from werkzeug.security import generate_password_hash, check_password_hash
from backend.db import get_db, transaction
from backend.services import create_patient
from backend.security import reveal
from backend.validation import Problem, choice


class AuthService:
    """Resolve database-owned roles and manage password-backed sessions; public signup is patient-only."""
    def __init__(self):
        # Unknown usernames still perform one password check to avoid a trivial timing leak.
        """Lazily create the dummy hash used to equalize unknown-account password checks."""
        self._dummy_hash = None

    @staticmethod
    def username(value):
        """Validate a bounded ASCII login identifier and return its case-insensitive canonical form."""
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._-]{3,64}', value):
            raise Problem('invalid_username')
        return value.lower()

    @staticmethod
    def password(value):
        """Validate length/nonblank content; preserve the password bytes represented by the supplied text."""
        if not isinstance(value, str) or not 12 <= len(value) <= 256 or not value.strip():
            raise Problem('invalid_password')
        return value  # Passwords are never stripped or normalized.

    def identity(self):
        """Reload active role/entity links each request and decrypt only this account’s display name."""
        account_id = session.get('account_id')
        if type(account_id) is not int:
            return None
        row = get_db().execute('SELECT a.*,p.first_name,p.last_name,v.name AS provider_name FROM Account a '
                               'LEFT JOIN Patient p USING(patient_id) LEFT JOIN Provider v USING(provider_id) '
                               'WHERE account_id=? AND active=1', (account_id,)).fetchone()
        if not row:
            return None
        row = reveal('Patient', row)
        if row['role'] == 'patient':
            name, entity_id = row['first_name'] + ' ' + row['last_name'], row['patient_id']
        elif row['role'] == 'provider':
            name, entity_id = row['provider_name'], row['provider_id']
        else:
            name, entity_id = row['username'], None
        return {'account_id': row['account_id'], 'role': row['role'], 'id': entity_id, 'name': name}

    def signup(self, form):
        # Public signup never links an existing record or accepts a privileged role.
        """Create encrypted profile and patient-only account atomically; rotate session/CSRF on success."""
        if any(key in form for key in ('role', 'patient_id', 'provider_id', 'account_id')):
            raise Problem('forbidden', 403)
        username = self.username(form.get('username'))
        password = self.password(form.get('password'))
        if password != form.get('password_confirm'):
            raise Problem('password_mismatch')
        password_hash = generate_password_hash(password, method='scrypt')
        try:
            with transaction() as db:
                if db.execute('SELECT 1 FROM Account WHERE username=?', (username,)).fetchone():
                    raise Problem('duplicate_signup', 409)
                patient_id = create_patient(form, db)
                account_id = db.execute("INSERT INTO Account(username,password_hash,role,patient_id) VALUES(?,?,'patient',?)",
                                        (username,password_hash,patient_id)).lastrowid
        except sqlite3.IntegrityError:
            raise Problem('duplicate_signup', 409) from None
        self._start_session(account_id)
        return patient_id

    def login(self, form):
        # No role/entity field is honored, including obsolete demo-identity tokens.
        """Verify scrypt password and active account; use one generic error for all invalid credentials."""
        username, password = form.get('username', ''), form.get('password', '')
        if not isinstance(password, str) or len(password) > 256:
            raise Problem('invalid_login', 401)
        row = get_db().execute('SELECT * FROM Account WHERE username=?', (username.lower(),)).fetchone()
        if self._dummy_hash is None:
            self._dummy_hash = generate_password_hash(secrets.token_urlsafe(32), method='scrypt')
        valid = check_password_hash(row['password_hash'] if row else self._dummy_hash, password)
        if not row or not valid or not row['active']:
            raise Problem('invalid_login', 401)
        self._start_session(row['account_id'])

    @staticmethod
    def _start_session(account_id):
        """Clear prior privilege/session state and issue a fresh CSRF token after authentication."""
        locale = session.get('locale')
        session.clear()
        if locale in ('en', 'ar'):
            session['locale'] = locale
        session['account_id'] = account_id
        session['csrf'] = secrets.token_hex(32)

    @staticmethod
    def logout():
        """Clear the signed session and its CSRF token; no clinical data is modified."""
        locale = session.get('locale')
        session.clear()
        if locale in ('en', 'ar'):
            session['locale'] = locale

    def provision(self, username, password, role, patient_id=None, provider_id=None):
        """Trusted local CLI/test operation. This is never exposed as an HTTP endpoint."""
        username = self.username(username)
        password = self.password(password)
        choice(role, ('patient', 'provider', 'worker'))
        if not ((role == 'patient' and patient_id is not None and provider_id is None)
                or (role == 'provider' and provider_id is not None and patient_id is None)
                or (role == 'worker' and patient_id is None and provider_id is None)):
            raise Problem('account_link')
        password_hash = generate_password_hash(password, method='scrypt')
        try:
            with transaction() as db:
                return db.execute('INSERT INTO Account(username,password_hash,role,patient_id,provider_id) VALUES(?,?,?,?,?)',
                                  (username,password_hash,role,patient_id,provider_id)).lastrowid
        except sqlite3.IntegrityError:
            raise Problem('account_link', 409) from None
