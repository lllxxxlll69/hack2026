import io
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, text

from backend.db import AccountToken, Base, Conversation, Document, Generated, Message, Session, User, engine, now
from backend.main import app, cleanup, migrate_account_confirmation
from backend.storage import read_file


@pytest.fixture
def client(monkeypatch):
    # Queue is paused for reproducible endpoint tests; model calls have separate tests.
    async def worker():
        import asyncio
        await asyncio.Future()
    monkeypatch.setattr('backend.main.worker', worker)
    Base.metadata.drop_all(engine)
    with TestClient(app) as client:
        yield client


def login(client, username='dean', password='TestBootstrap-LongPassword-2026'):
    r = client.post('/api/auth/login', json={'username':username, 'password':password})
    assert r.status_code == 200, r.text
    return {'Authorization':'Bearer ' + r.json()['token']}


def make_student(client, dean, username):
    r = client.post('/api/users', headers=dean, json={'username':username, 'name':'Тестовый студент', 'email':'test@example.local', 'password':'Temporary-LongPassword', 'role':'student'})
    assert r.status_code == 200, r.text
    assert r.json()['user']['verified'] is True
    assert 'confirmation_code' not in r.json()
    client.cookies.clear()
    headers = login(client, username, 'Temporary-LongPassword')
    assert client.get('/api/conversations', headers=headers).status_code == 403
    assert client.post('/api/auth/verify', json={'token':'unused'}).status_code == 404
    assert client.post('/api/auth/password', headers=headers, json={'old_password':'Temporary-LongPassword', 'password':'Permanent-LongPassword'}).status_code == 200
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    return login(client, username, 'Permanent-LongPassword')


def test_removed_confirmation_migrates_existing_accounts_without_changing_access(client):
    with Session() as db:
        account = User(username='legacy-student', name='Legacy', email='', password='unchanged-hash',
                       role='student', active=False, verified=False, must_change=True)
        db.add(account)
        db.flush()
        db.add(AccountToken(id='old-verification', user_id=account.id, purpose='verify',
                            expires=now() + timedelta(hours=1)))
        db.add(AccountToken(id='keep-reset', user_id=account.id, purpose='reset',
                            expires=now() + timedelta(hours=1)))
        db.commit()
        migrate_account_confirmation(db)
        db.commit()
        assert account.verified is True
        assert account.active is False
        assert account.must_change is True
        assert account.password == 'unchanged-hash'
        assert account.role == 'student'
        assert db.get(AccountToken, 'old-verification') is None
        assert db.get(AccountToken, 'keep-reset') is not None


def test_account_authorization_chat_handoff_and_review(client):
    dean = login(client)
    student = make_student(client, dean, 'student01')
    other = make_student(client, dean, 'student02')
    r = client.post('/api/conversations', headers=student, json={'text':'Проверка справки'})
    cid = r.json()['id']
    assert client.get('/api/conversations/' + cid, headers=other).status_code == 404
    assert client.get('/api/users', headers=student).status_code == 403
    assert client.post(f'/api/conversations/{cid}/messages', headers=student, json={'text':'Переведи меня на деканат'}).status_code == 200
    assert client.get('/api/conversations/' + cid, headers=dean).json()['status'] == 'dean'
    assert client.post(f'/api/conversations/{cid}/messages', headers=dean, json={'text':'Добрый день, пришлите справку.'}).status_code == 200
    r = client.get('/api/conversations/' + cid, headers=student).json()
    assert any(m['sender'] == 'dean' for m in r['messages'])
    assert client.post(f'/api/conversations/{cid}/review', headers=student, json={'decision':'approved','comment':'yes'}).status_code == 403
    assert client.post(f'/api/conversations/{cid}/review', headers=dean, json={'decision':'approved','comment':'Ответ подтверждён сотрудником'}).status_code == 200
    assert client.get('/api/stats', headers=dean).json()['events']['resolved'] == 1
    assert client.post(f'/api/conversations/{cid}/messages', headers=student, json={'text':'more'}).status_code == 409


def test_encryption_retention_and_template_fields(client):
    dean = login(client)
    student = make_student(client, dean, 'student03')
    cid = client.post('/api/conversations', headers=student, json={'text':'Секретный документ'}).json()['id']
    png = io.BytesIO()
    Image.new('RGB', (30, 30), 'white').save(png, format='PNG')
    r = client.post(f'/api/conversations/{cid}/documents', headers=student, files={'file':('scan.png',png.getvalue(),'image/png')})
    did = r.json()['id']
    with Session() as db:
        doc = db.get(Document, did)
        assert read_file(doc.file_key) == png.getvalue()
        assert b'PNG' not in (doc.file_key.encode())
        doc.state = 'error'
        db.commit()
    fields = {'student_name':'Иванов Иван Иванович', 'group':'ЭК-22', 'course':'2', 'leave_reason':'по здоровью', 'leave_start':'2026-09-01', 'leave_end':'2027-08-31', 'application_date':'2026-08-30', 'signature_present':True}
    r = client.patch('/api/documents/' + did + '/fields', headers=dean, json={'document_type':'academic_leave_application','fields':fields})
    assert r.status_code == 200, r.text
    tid = client.post('/api/templates', headers=dean, files={'file':('template.md','Студент: {{ student_name }}'.encode())}, data={'title':'Заявление'}).json()['id']
    report = client.get('/api/conversations/' + cid, headers=student).json()['documents'][0]['report']
    assert report['available']
    assert report['required_count'] == report['present_count'] == len(fields)
    assert any(check['rule'] == '4.2' and check['quote'] for check in report['checks'])
    generated = client.post(f'/api/conversations/{cid}/generate/{tid}', headers=dean)
    assert generated.status_code == 200, generated.text
    gid = generated.json()['id']
    assert 'Иванов' in client.get('/api/generated/' + gid, headers=student).text
    invalid = client.post('/api/templates', headers=dean, files={'file':('bad.md',b'{{ unknown_field }}')}, data={'title':'bad'}).json()['id']
    assert client.post(f'/api/conversations/{cid}/generate/{invalid}', headers=dean).status_code == 422
    with engine.connect() as conn:
        raw = conn.execute(text('select fields from documents')).scalar()
        assert 'Иванов' not in raw
        assert raw.startswith('gAAAA')
    with Session() as db:
        conv = db.get(Conversation, cid)
        conv.expires_at = now() - timedelta(seconds=1)
        db.commit()
    cleanup()
    assert client.get('/api/conversations/' + cid, headers=student).status_code == 404
    with Session() as db:
        assert db.get(Document, did) is None
        assert db.get(Generated, gid) is None
        assert not list(db.scalars(select(Message)))


def test_origin_protection_and_password_lockout(client):
    r = client.post('/api/auth/login', headers={'Origin':'https://evil.example'}, json={'username':'dean','password':'TestBootstrap-LongPassword-2026'})
    assert r.status_code == 403
    for _ in range(5):
        assert client.post('/api/auth/login', json={'username':'dean','password':'wrong'}).status_code == 401
    assert client.post('/api/auth/login', json={'username':'dean','password':'TestBootstrap-LongPassword-2026'}).status_code == 429


def test_clause_search_requires_auth_and_uses_live_rules(client):
    assert client.get('/api/knowledge/search?q=штамп').status_code == 401
    dean = login(client)
    student = make_student(client, dean, 'search-student')
    result = client.get('/api/knowledge/search', headers=student, params={'q':'штамп'}).json()
    assert any(hit['rule'] == '3.3' for hit in result['results'])
    exact = client.get('/api/knowledge/search?q=3.2', headers=student).json()['results']
    assert len(exact) == 1
    assert exact[0]['rule'] == '3.2'
    assert 'подпись' in exact[0]['quote'].lower()
    assert client.get('/api/knowledge/search?q=999.9', headers=student).json()['results'] == []
    assert client.get('/api/knowledge/search', headers=student, params={'q':'x'*301}).status_code == 422
    assert client.get('/api/knowledge/search?q=штамп&document_id=unknown', headers=student).json()['results'] == []
