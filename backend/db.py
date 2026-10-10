"""SQLite v2 only. Never migrate or recreate an existing database."""
import sqlite3
from contextlib import closing
from pathlib import Path
from flask import current_app, g

ROOT = Path(__file__).resolve().parent.parent


def connect(path):
    db = sqlite3.connect(str(path), timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=5000')
    return db


def initialize(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents concurrent first boots from rerunning the schema.
    try:
        with path.open('xb'):
            pass
    except FileExistsError:
        pass
    else:
        with closing(connect(path)) as db:
            db.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
    with closing(connect(path)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version != 2:
            raise RuntimeError(f'{path}: expected SQLite user_version 2, found {version}. '
                               'Preserve this database; select a NEW DATABASE path or apply an explicit reviewed migration.')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Database foreign key check failed; preserve the database and inspect its integrity.')


def get_db():
    if 'db' not in g:
        g.db = connect(current_app.config['DATABASE'])
    return g.db


def close_db(_error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()
