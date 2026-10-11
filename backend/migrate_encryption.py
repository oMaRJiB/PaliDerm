"""Copy-only plaintext→encrypted v4 migration. Stop all writers before running.

Source SQLite is copied into RAM, transformed there, then VACUUMed before an
on-disk backup. This avoids leaving old plaintext in target SQLite free pages,
journals or temporary copies. One directory rename publishes DB+images together.
"""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from backend.db import ROOT, _apply_auth, apply_encryption_schema, verify_encryption_key
from backend.preprocessing import normalize_gender, SYMPTOM_ORDER
from backend.security import Cipher, TEXT_FIELDS, EncryptionError
from backend.images import ImageStorage
from backend.validation import Problem

PRIMARY_KEYS = {'Patient':'patient_id','DermCase':'case_id','Symptom':'symptom_id',
                'ProviderReview':'review_id','Diagnosis':'diagnosis_id','TreatmentPlan':'treatment_id',
                'AIAnalysis':'analysis_id','AICandidate':'candidate_id'}


class MigrationError(RuntimeError):
    """Actionable operator error containing no clinical values, image IDs or keys."""


def migrate(source_db, source_uploads, destination, encryption):
    """Create destination/demo.sqlite3 + uploads; return counts without sensitive data.

    Requires unused destination and source v2/v3. Raises on missing/corrupt images,
    schema/integrity problems or any failed round trip. Sources remain untouched;
    only this call's staging directory is cleaned up on failure.
    """
    source_db, source_uploads, destination = map(lambda value: Path(value).resolve(),
                                                (source_db, source_uploads, destination))
    if not source_db.is_file():
        raise MigrationError('Source database is missing; check --source-db. No database was created.')
    if destination.exists():
        raise MigrationError('Destination already exists; select an unused --destination. '
                             'If migration already succeeded, launch the encrypted dataset instead of migrating again.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.encryption-stage-', dir=destination.parent))
    staging.chmod(0o700)
    try:
        with closing(sqlite3.connect(':memory:')) as memory:
            memory.row_factory = sqlite3.Row
            memory.execute('PRAGMA temp_store=MEMORY')
            memory.execute('PRAGMA foreign_keys=ON')
            with closing(sqlite3.connect(source_db.as_uri() + '?mode=ro', uri=True)) as source:
                source.backup(memory)
            version = memory.execute('PRAGMA user_version').fetchone()[0]
            if version not in (2, 3):
                raise MigrationError('Copy migration accepts only plaintext v2/v3 sources. '
                                     'An encrypted v4 dataset should be launched with its existing key.')
            if memory.execute('PRAGMA foreign_key_check').fetchone():
                raise MigrationError('Source has foreign key violations; preserved without migration.')
            if version == 2:
                _apply_auth(memory)
            originals = {table: [dict(row) for row in memory.execute(f'SELECT * FROM {table}')] for table in PRIMARY_KEYS}
            # Unknown tables could contain unprotected PII: require an explicit mapping.
            expected = {*PRIMARY_KEYS, 'Account', 'BodySite', 'Lesion', 'LesionImage', 'Provider'}
            tables = {row[0] for row in memory.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables != expected:
                raise MigrationError('Source contains unmapped tables; document their encryption before migration.')
            # An unknown column could be an unprotected medical-history extension.
            with closing(sqlite3.connect(':memory:')) as reference:
                reference.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
                _apply_auth(reference)
                for table in expected:
                    actual = [row[1] for row in memory.execute(f'PRAGMA table_info({table})')]
                    known = [row[1] for row in reference.execute(f'PRAGMA table_info({table})')]
                    if actual != known:
                        raise MigrationError('Source contains unmapped columns; explicit encryption mapping required.')
            apply_encryption_schema(memory, encryption)
            with memory:
                for table, rows in originals.items():
                    for original in rows:
                        values = dict(original)
                        updates = {}
                        if table == 'Patient':
                            canonical = normalize_gender(values['sex'], legacy=True)
                            old = values['sex']
                            if old is not None and old.strip().casefold() not in ('female','male','unknown','f','m','','unknown/prefer not to say','prefer not to say'):
                                updates['legacy_sex_encrypted'] = encryption.encrypt(old, 'Patient.legacy_sex')
                            values['sex'] = canonical
                        for field in TEXT_FIELDS[table]:
                            updates[field] = encryption.text(table, field, values[field])
                        if table == 'DermCase':
                            updates['encrypted_duration'] = encryption.encrypt(values['duration_days'], 'DermCase.duration_days')
                            updates['duration_days'] = None
                        if table == 'Symptom':
                            updates['encrypted_answers'] = encryption.encrypt({key:values[key] for key in SYMPTOM_ORDER}, 'Symptom.answers')
                            updates.update({key:None for key in SYMPTOM_ORDER})
                        if table == 'AIAnalysis':
                            updates['input_snapshot_json'] = json.dumps({'encrypted': encryption.encrypt(values['input_snapshot_json'], 'AIAnalysis.input_snapshot_json')})
                        columns = ','.join(f'{field}=?' for field in updates)
                        key = PRIMARY_KEYS[table]
                        memory.execute(f'UPDATE {table} SET {columns} WHERE {key}=?', (*updates.values(), original[key]))
                # Verify all clinical fields before publishing; exact free text must survive.
                for table, rows in originals.items():
                    key = PRIMARY_KEYS[table]
                    for original in rows:
                        row = memory.execute(f'SELECT * FROM {table} WHERE {key}=?', (original[key],)).fetchone()
                        decoded = encryption.reveal(table, row)
                        expected_row = dict(original)
                        if table == 'Patient':
                            expected_row['sex'] = normalize_gender(original['sex'], legacy=True)
                        if any(decoded[field] != value for field, value in expected_row.items()):
                            raise MigrationError('Encrypted field verification failed; source unchanged.')
            upload_target = staging / 'uploads'
            upload_target.mkdir(mode=0o700)
            storage = ImageStorage({'UPLOAD_DIR':upload_target,'MAX_IMAGE_BYTES':8*1024*1024,'MAX_IMAGE_COUNT':12}, encryption)
            image_rows = memory.execute('SELECT * FROM LesionImage').fetchall()
            copied_images = {}
            for row in image_rows:
                # Validate server-generated basename before reading a source file.
                try:
                    basename = storage.path(row['image_uri']).name
                except Problem:
                    raise MigrationError('A source image storage identifier is invalid; '
                                         'repair its mapping before migration. No arbitrary paths are read.') from None
                reference = (row['content_sha256'], row['mime_type'])
                if basename in copied_images:
                    # SQL permits several image rows to reference one storage object.
                    # Copy it once, but reject contradictory hashes/MIME on any row.
                    if copied_images[basename] != reference:
                        raise MigrationError('Source image references disagree on hash or MIME type; '
                                             'repair the conflicting metadata before migration.')
                    continue
                source_path = source_uploads / basename
                if source_path.is_symlink():
                    raise MigrationError('Migration refuses image symlinks; supply original private image files.')
                if not source_path.is_file():
                    raise MigrationError('A referenced source image is missing; check --source-uploads '
                                         'and restore the original file before migration.')
                raw = source_path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != row['content_sha256']:
                    raise MigrationError('Source image hash mismatch; no encrypted dataset published.')
                target = storage.path(basename)
                with target.open('xb') as file:
                    file.write(encryption.encrypt_image(raw, basename))
                target.chmod(0o600)
                if storage.read_original(basename, row['content_sha256']) != raw:
                    raise MigrationError('Encrypted image round trip failed.')
                copied_images[basename] = reference
            verify_encryption_key(memory, encryption)
            if memory.execute('PRAGMA foreign_key_check').fetchone():
                raise MigrationError('Encrypted migration failed foreign key verification.')
            memory.execute('VACUUM')  # rebuild pages so stale plaintext never enters target
            target_db = staging / 'demo.sqlite3'
            with closing(sqlite3.connect(target_db)) as target:
                memory.backup(target)
            target_db.chmod(0o600)
            report = {'version':4, 'records':{table:len(rows) for table,rows in originals.items()},
                      'images':len(image_rows), 'image_files':len(copied_images)}
            report_path = staging / 'migration-report.json'
            report_path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            report_path.chmod(0o600)
        if destination.exists():
            raise MigrationError('Destination appeared during migration; refusing overwrite.')
        os.rename(staging, destination)
        return report
    except BaseException:
        shutil.rmtree(staging)
        raise


def main():
    """Read operator-selected paths/key; report counts only, never records or secrets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True)
    parser.add_argument('--source-uploads', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    try:
        report = migrate(args.source_db, args.source_uploads, args.destination, Cipher.from_config())
    except (EncryptionError, MigrationError) as error:
        # Only our controlled messages are shown; arbitrary OS/SQL errors can leak data.
        parser.exit(1, f'Migration failed; sources preserved. {error}\n')
    except (RuntimeError, OSError, sqlite3.Error, Problem):
        parser.exit(1, 'Migration failed; sources preserved. Check file permissions, schema and image integrity.\n')
    print(f"Verified encrypted v4 dataset: {sum(report['records'].values())} clinical records, {report['images']} images.")


if __name__ == '__main__':
    main()
