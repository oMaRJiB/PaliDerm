"""Real HTTP + child-process restart in an isolated temporary database; no demo data changes."""
import os
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
import http_smoke as smoke


def run():
    with tempfile.TemporaryDirectory(prefix='paliderm-auth-http-') as directory:
        root=Path(directory)
        password=secrets.token_urlsafe(24)
        secret=secrets.token_hex(32)
        config={'DATABASE':str(root/'test.sqlite3'),'UPLOAD_DIR':str(root/'uploads'),'SECRET_KEY':secret,'ENCRYPTION_KEY':Fernet.generate_key().decode('ascii'),'ENCRYPTION_KEY_FILE':''}
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
            smoke.create('http-clinician',password)
        finally:
            process.terminate()
            process.wait(timeout=5)
        process=start()
        try:
            smoke.verify()
        finally:
            process.terminate()
            process.wait(timeout=5)
        print('PASS: credential-based signup/login/logout → complete review workflow → actual child-process restart. Existing demo database untouched.')


if __name__=='__main__':
    run()
