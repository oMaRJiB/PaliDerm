"""SQLite connection invariants and additive v2→v3→encrypted-v4 schema setup."""
import argparse
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from flask import current_app, g

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_VERSION = 4


def connect(path):
    """Open raw SQLite with row access, foreign keys and bounded lock waits; caller closes it."""
    db = sqlite3.connect(str(path), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db


def _apply_auth(db):
    # A single CREATE statement; keep transaction control in Python for rollback.
    """Apply the one-table v2→v3 extension within a rollback-capable transaction."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise RuntimeError('Authentication migration requires version 2; no changes made.')
        db.execute((ROOT / 'auth_migration.sql').read_text(encoding='utf-8'))
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Foreign key check failed; authentication migration rolled back.')
        db.execute('PRAGMA user_version=3')


def migrate_auth(path):
    """Back up and upgrade v2 authentication only; return backup path or None if already upgraded."""
    path = (ROOT / path).resolve()
    if not path.is_file():
        raise RuntimeError(f'{path}: database does not exist; migration will not create or replace it.')
    with closing(connect(path)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version in (3, 4):
            return None
        if version != 2:
            raise RuntimeError(f'{path}: expected version 2 for migration, found {version}. Preserve and inspect this database.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Existing database has foreign key violations; no changes made.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = path.with_name(f'{path.stem}.before-auth-v3-{stamp}-{uuid4().hex[:8]}.sqlite3')
        with backup.open('xb'):
            pass
        os.chmod(backup, 0o600)
        with closing(sqlite3.connect(backup)) as target:
            db.backup(target)
        _apply_auth(db)
        return backup


def apply_encryption_schema(db, encryption):
    """Add v4 companions/marker to a new or migration-copy v3 database atomically."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('PRAGMA user_version').fetchone()[0] != 3:
            raise RuntimeError('Encryption extension requires runtime v3.')
        for statement in (ROOT / 'encryption_migration.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip():
                db.execute(statement)
        db.execute('INSERT INTO EncryptionConfig(singleton,key_check) VALUES(1,?)',
                   (encryption.encrypt('paliderm-v4', 'key-check'),))
        install_encryption_guards(db)
        db.execute('PRAGMA user_version=4')


def install_encryption_guards(db):
    """Reject accidental plaintext writes without altering the original table constraints."""
    from backend.security import TEXT_FIELDS, PREFIX
    for table, fields in TEXT_FIELDS.items():
        conditions = [f"(NEW.{field} IS NOT NULL AND substr(NEW.{field},1,10) != '{PREFIX}')" for field in fields]
        if table == 'Patient':
            conditions.append(f"(NEW.legacy_sex_encrypted IS NOT NULL AND substr(NEW.legacy_sex_encrypted,1,10) != '{PREFIX}')")
        if table == 'DermCase':
            conditions += [f"COALESCE(substr(NEW.encrypted_duration,1,10),'') != '{PREFIX}'", 'NEW.duration_days IS NOT NULL']
        if table == 'Symptom':
            conditions += [f"COALESCE(substr(NEW.encrypted_answers,1,10),'') != '{PREFIX}'"]
            conditions += [f'NEW.{key} IS NOT NULL' for key in ('itching','pain','bleeding','discharge','fever','rapidly_worsening')]
        if table == 'AIAnalysis':
            conditions += [f"COALESCE(substr(json_extract(NEW.input_snapshot_json,'$.encrypted'),1,10),'') != '{PREFIX}'"]
        # Identifiers above come only from our fixed field whitelist, never a request.
        for operation in ('INSERT', 'UPDATE'):
            db.execute(f"CREATE TRIGGER encrypted_{table}_{operation} BEFORE {operation} ON {table} "
                       f"WHEN {' OR '.join(conditions)} BEGIN SELECT RAISE(ABORT,'Encrypted fields required'); END")


def verify_encryption_key(db, encryption):
    """Fail startup before serving any data when the environment key is incorrect."""
    from backend.security import EncryptionError
    row = db.execute('SELECT key_check FROM EncryptionConfig WHERE singleton=1').fetchone()
    if not row or encryption.decrypt(row[0], 'key-check') != 'paliderm-v4':
        raise EncryptionError('Encryption key verification failed.')


def initialize(path, encryption):
    """Create only absent databases; require v4 plus a matching key for existing encrypted data."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb'):
            pass
    except FileExistsError:
        pass
    else:
        try:
            path.chmod(0o600)
            with closing(connect(path)) as db:
                db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
                _apply_auth(db)
                apply_encryption_schema(db, encryption)
        except BaseException:
            # Only this call's new file is disposable. Otherwise a failed fresh
            # setup looks like legacy v3 data and wrongly demands copy migration.
            path.unlink(missing_ok=True)
            raise
    with closing(connect(path)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version != RUNTIME_VERSION:
            if version == 3:
                raise RuntimeError('The selected DATABASE is plaintext runtime v3. If already migrated, set '
                                   'DATABASE=instance/encrypted/demo.sqlite3 and UPLOAD_DIR=instance/encrypted/uploads. '
                                   'Otherwise stop the server and run the explicit copy migration: '
                                   'python -m backend.migrate_encryption (see docs/ENCRYPTION.md). No data was modified.')
            if version == 2:
                raise RuntimeError(f'{path}: authentication requires user_version 3; found 2. Stop the server, then run '
                                   f'.venv/bin/python -m backend.db migrate-auth --database "{path}". A backup is created first.')
            raise RuntimeError(f'{path}: expected SQLite user_version 4, found {version}. '
                               'Preserve this database; select a NEW DATABASE path or apply an explicit reviewed migration.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Database foreign key check failed; preserve the database and inspect its integrity.')
        verify_encryption_key(db, encryption)


def get_db():
    """Return this application request/context SQLite connection; never a global shared connection."""
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def close_db(_error=None):
    """Close the context-owned connection at teardown, including after failed requests."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


@contextmanager
def transaction():
    """Yield one write transaction; roll back every exception and commit only successful completion."""
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Explicit additive migration; stop the server first.')
    parser.add_argument('command', choices=['migrate-auth'])
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    backup = migrate_auth(args.database)
    print(f'Migrated to v3; backup: {backup}' if backup else 'Already v3; no changes made.')
