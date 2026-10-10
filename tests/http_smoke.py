"""Real HTTP workflow; run `create`, restart the server, then run `verify`."""
import argparse
import hashlib
import http.cookiejar
import io
import json
import re
import uuid
from pathlib import Path
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.parse import urlencode, urlparse
from PIL import Image

BASE = 'http://127.0.0.1:5000'
STATE = Path(__file__).resolve().parents[1] / 'instance/http-smoke.json'
ARABIC = '  مريض تجريبي — شكوى عربية محفوظة  '
jar = http.cookiejar.CookieJar()
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


def login(identity):
    return post('/login', {'identity':identity})


def create():
    path, page = post('/patients/new', {'first_name':ARABIC,'last_name':'HTTP Synthetic',
                                       'date_of_birth':'1999-02-28','phone':'+1-202-555-0199'}, '/patients/new')
    patient_id = int(path.rsplit('/',1)[1])
    path, page = post(f'/patients/{patient_id}/cases', {'chief_complaint':ARABIC,'duration_days':'7'})
    case_id = int(path.rsplit('/',1)[1])
    post(f'/cases/{case_id}/draft', {'chief_complaint':ARABIC,'duration_days':'7', 'itching':'','pain':'0',
                                    'body_sites':['8','7'],'additional_notes':ARABIC})
    page = get(f'/cases/{case_id}')
    lesion_id = re.search(r'<select name="lesion_id"><option value="(\d+)"',page)[1]
    im = Image.new('RGB',(64,64),'gray')
    stream = io.BytesIO()
    im.save(stream,format='PNG')
    boundary = 'smoke-'+uuid.uuid4().hex
    parts = []
    for name,value in {'csrf':csrf(page),'lesion_id':lesion_id}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for n in range(2):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="images"; filename="synthetic-{n}.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+stream.getvalue()+b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    req = Request(BASE+f'/cases/{case_id}/images',data=b''.join(parts),headers={'Content-Type':f'multipart/form-data; boundary={boundary}'})
    with http.open(req,timeout=10) as response:
        page = response.read().decode()
    assert page.count('<img ') == 2
    post(f'/cases/{case_id}/submit',{'consent':'1'})
    login('provider:1')
    assert f'/cases/{case_id}' in get('/queue')
    post(f'/cases/{case_id}/transition',{'action':'claim'})
    post(f'/cases/{case_id}/review', {'decision':'confirmed','triage_level':'undetermined','patient_message':ARABIC,
                                    'clinical_notes':'PRIVATE HTTP SMOKE NOTE','diagnosis_0':'Synthetic clinician documentation',
                                    'certainty_0':'provisional','primary':'0','instructions_0':'Synthetic treatment instructions',
                                    'referral_required':'1','referral_destination':'Synthetic external clinic',
                                    'referral_reason':'Synthetic referral demonstration','followup_date':'2026-12-15','review_base':'0'})
    login(f'patient:{patient_id}')
    page = get(f'/cases/{case_id}')
    assert ARABIC in page and 'Synthetic treatment instructions' in page and 'PRIVATE HTTP SMOKE NOTE' not in page
    image_id = int(re.search(r'<img src="/images/(\d+)"',page)[1])
    with http.open(BASE+f'/images/{image_id}') as response:
        digest = hashlib.sha256(response.read()).hexdigest()
    STATE.write_text(json.dumps({'patient_id':patient_id,'case_id':case_id,'image_id':image_id,'sha256':digest},ensure_ascii=False),encoding='utf-8')
    print(f'PASS: real HTTP registration → draft → two images → consent → queue → clinician diagnosis/treatment/referral → patient outcome. Case {case_id}.')


def verify():
    data = json.loads(STATE.read_text())
    login(f'patient:{data["patient_id"]}')
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
    create() if parser.parse_args().action == 'create' else verify()
