"""Real HTTP + child-process restart in an isolated temporary database; no demo data changes."""
import os
import argparse
import json
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from cryptography.fernet import Fernet
from app import create_app
from backend.auth import AuthService
from backend.db import get_db, transaction
from backend.security import reveal
import http_smoke as smoke


def run(with_model=False):
    """Use a disposable encrypted dataset; --with-model also checks actual saved inference."""
    with tempfile.TemporaryDirectory(prefix='paliderm-auth-http-') as directory:
        root=Path(directory)
        password=secrets.token_urlsafe(24)
        secret=secrets.token_hex(32)
        config={'DATABASE':str(root/'test.sqlite3'),'UPLOAD_DIR':str(root/'uploads'),'SECRET_KEY':secret,'ENCRYPTION_KEY':Fernet.generate_key().decode('ascii'),'ENCRYPTION_KEY_FILE':''}
        if with_model:
            config.update(MODEL_PATH=str(Path(__file__).resolve().parents[1]/'notebooks/SCIN_custom_model.keras'),
                          AI_TIMEOUT_SECONDS='90')
        app=create_app(config)
        with app.app_context():
            with transaction() as db:
                provider_id=db.execute("INSERT INTO Provider(name) VALUES('Synthetic HTTP clinician')").lastrowid
            AuthService().provision('http-clinician',password,'provider',provider_id=provider_id)
        smoke.BASE='http://127.0.0.1:5001'
        smoke.STATE=root/'http-smoke.json'
        smoke.COOKIE=root/'http-smoke.cookies'
        smoke.jar.filename=str(smoke.COOKIE)
        env={**os.environ,**config}
        def start():
            process=subprocess.Popen([sys.executable,'-m','flask','--app','app','run','--host','127.0.0.1','--port','5001'],
                                     env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Test server exited; check whether port 5001 is already in use.')
                    try:
                        with urlopen(smoke.BASE+'/login',timeout=.2) as response:
                            if response.status==200:
                                return process
                    except (URLError,TimeoutError):
                        time.sleep(.05)
                raise RuntimeError('Test server did not become ready.')
            except BaseException:
                process.terminate()
                process.wait(timeout=5)
                raise
        process=start()
        try:
            smoke.create('http-clinician',password,analyze=with_model)
        finally:
            process.terminate()
            process.wait(timeout=5)
        process=start()
        try:
            smoke.verify()
            if with_model:
                with app.app_context():
                    db = get_db()
                    analysis = reveal('AIAnalysis', db.execute('SELECT * FROM AIAnalysis').fetchone())
                    assert analysis['status'] == 'completed'
                    triage = json.loads(analysis['rationale'])['triage']
                    assert triage['triage_method'] == 'rules_with_model_input'
                    assert triage['triage_reasons']
                    assert type(triage['needs_manual_review']) is bool
                    assert analysis['triage_level'] == (
                        'undetermined' if triage['triage_level'] == 'routine' and triage['needs_manual_review']
                        else {'emergency':'red','urgent':'amber','routine':'green'}[triage['triage_level']])
                    snapshot = json.loads(analysis['input_snapshot_json'])
                    assert len(snapshot['model_metadata']) == 36
                    assert snapshot['model_metadata']['condition_duration'] == 'ONE_TO_FOUR_WEEKS'
                    assert snapshot['model_metadata']['sex_at_birth'] == 'OTHER_OR_UNSPECIFIED'
                    assert snapshot['model_metadata']['age_group'] == 'AGE_18_TO_29'
                    patient_answers = reveal('Symptom',db.execute('SELECT * FROM Symptom').fetchone())['model_metadata']
                    assert snapshot['model_metadata'] == patient_answers
                    assert db.execute('SELECT count(*) FROM AICandidate').fetchone()[0] == len(app.config['AI_ADAPTER'].classes)
                    assert not db.execute('PRAGMA foreign_key_check').fetchall()
                print('PASS: actual server restart preserves encrypted patient model answers, real predictions and prototype triage.')
        finally:
            process.terminate()
            process.wait(timeout=5)
        print('PASS: credential-based signup/login/logout → complete review workflow → actual child-process restart. Existing demo database untouched.')


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-model', action='store_true', help='Also run the selected existing SCIN custom model on synthetic images.')
    run(parser.parse_args().with_model)
