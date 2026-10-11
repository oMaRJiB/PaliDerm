"""Real HTTP workflow; run `create`, restart the server, then run `verify`."""
import argparse
import hashlib
import http.cookiejar
import io
import json
import re
import os
import secrets
import getpass
import uuid
from pathlib import Path
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.parse import urlencode, urlparse
from PIL import Image

BASE = os.environ.get('SMOKE_BASE_URL', 'http://127.0.0.1:5000')
STATE = Path(__file__).resolve().parents[1] / 'instance/http-smoke.json'
ARABIC = '  مريض تجريبي — شكوى عربية محفوظة  '
COOKIE = STATE.with_name('http-smoke.cookies')
jar = http.cookiejar.MozillaCookieJar(str(COOKIE))
http = build_opener(HTTPCookieProcessor(jar))


def get(path):
    with http.open(BASE+path, timeout=10) as result:
        return result.read().decode('utf-8')


def csrf(page):
    return re.search(r'name="csrf" value="([a-f0-9]+)"', page)[1]


def post(path, values, source='/login'):
    values = {**values, 'csrf':csrf(get(source))}
    data = urlencode(values, doseq=True).encode()
    with http.open(BASE+path, data=data, timeout=10) as result:
        return urlparse(result.url).path, result.read().decode('utf-8')


def login(username, password):
    return post('/login', {'username':username, 'password':password})


def create(provider_username, provider_password):
    username = 'smoke-' + uuid.uuid4().hex[:12]
    patient_password = secrets.token_urlsafe(24)
    path, page = post('/patients/new', {'username':username, 'password':patient_password, 'password_confirm':patient_password,
                                       'first_name':ARABIC,'last_name':'HTTP Synthetic',
                                       'date_of_birth':'1999-02-28','phone':'+1-202-555-0199'}, '/patients/new')
    patient_id = int(path.rsplit('/',1)[1])
    path, page = post(f'/patients/{patient_id}/cases', {'chief_complaint':ARABIC,'duration_days':'7'})
    case_id = int(path.rsplit('/',1)[1])
    post(f'/cases/{case_id}/draft', {'chief_complaint':ARABIC,'duration_days':'7', 'itching':'','pain':'0',
                                    'body_sites':['8','7'],'additional_notes':ARABIC})
    page = get(f'/cases/{case_id}')
    # Exercise the current single-page intake with both existing-file and camera fields.
    im = Image.new('RGB',(64,64),'gray')
    stream = io.BytesIO()
    im.save(stream,format='PNG')
    boundary = 'smoke-'+uuid.uuid4().hex
    parts = []
    for name,value in {'csrf':csrf(page),'chief_complaint':ARABIC,'duration_days':'7','itching':'','pain':'0','body_sites':'8','photo_body_site':'8','additional_notes':ARABIC,'intake_action':'submit','consent':'1'}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for n in range(2):
        field_name = 'images' if n == 0 else 'camera'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="synthetic-{n}.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+stream.getvalue()+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req = Request(BASE+f'/cases/{case_id}/intake',data=b''.join(parts),headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    with http.open(req,timeout=10) as response:
        page = response.read().decode()
    assert page.count('<img ') == 2
    post(f'/cases/{case_id}/submit',{'consent':'1'})
    post('/logout', {})
    login(provider_username, provider_password)
    assert f'/cases/{case_id}' in get('/queue')
    post(f'/cases/{case_id}/transition',{'action':'claim'})
    post(f'/cases/{case_id}/review', {'decision':'confirmed','triage_level':'undetermined','patient_message':ARABIC,
                                    'clinical_notes':'PRIVATE HTTP SMOKE NOTE','diagnosis_0':'Synthetic clinician documentation',
                                    'certainty_0':'provisional','primary':'0','instructions_0':'Synthetic treatment instructions',
                                    'referral_required':'1','referral_destination':'Synthetic external clinic',
                                    'referral_reason':'Synthetic referral demonstration','followup_date':'2026-12-15','review_base':'0'})
    post('/logout', {})
    login(username, patient_password)
    page = get(f'/cases/{case_id}')
    assert ARABIC in page and 'Synthetic treatment instructions' in page and 'PRIVATE HTTP SMOKE NOTE' not in page
    image_id = int(re.search(r'<img src="/images/(\d+)"',page)[1])
    with http.open(BASE+f'/images/{image_id}') as response:
        digest = hashlib.sha256(response.read()).hexdigest()
    COOKIE.parent.mkdir(parents=True, exist_ok=True)
    jar.save(ignore_discard=True, ignore_expires=True)
    os.chmod(COOKIE, 0o600)
    STATE.write_text(json.dumps({'patient_id':patient_id,'case_id':case_id,'image_id':image_id,'sha256':digest},ensure_ascii=False),encoding='utf-8')
    print(f'PASS: real HTTP registration → draft → two images → consent → queue → clinician diagnosis/treatment/referral → patient outcome. Case {case_id}.')


def verify():
    data = json.loads(STATE.read_text())
    jar.load(ignore_discard=True, ignore_expires=True)
    page = get(f'/cases/{data["case_id"]}')
    assert ARABIC in page and 'Synthetic treatment instructions' in page
    assert 'Synthetic external clinic' in page and 'Provisional' in page
    assert 'PRIVATE HTTP SMOKE NOTE' not in page
    with http.open(BASE+f'/images/{data["image_id"]}') as response:
        assert hashlib.sha256(response.read()).hexdigest() == data['sha256']
    print('PASS: after actual server process restart, Arabic text, review, treatments, referral, and identical image bytes persist.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['create','verify'])
    parser.add_argument('--provider-username',default='clinician1')
    args=parser.parse_args()
    if args.action=='create':
        create(args.provider_username,getpass.getpass('Provisioned clinician password: '))
    else:
        verify()
