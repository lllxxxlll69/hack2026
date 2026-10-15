import asyncio
import io
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from docxtpl import DocxTemplate
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, func

from backend import ai
from backend.evidence import document_report, rank_clauses
from backend.config import ROOT, settings
from backend.db import (AccountToken, Audit, Base, Conversation, Document, DocumentType, Generated,
                        Knowledge, LoginSession, Message, Metric, Session, Template, User,
                        audit, engine, get_db, metric, now, uid)
from backend.logic import (MISSING, built_in_types, normalize_fields, parse_rules,
                           requests_handoff, validate_fields)
from backend.security import (account_token, check_password, consume_token, current_user,
                              dean_user, dummy_hash, hasher, new_session, ready_user,
                              revoke_sessions, send_code, verify)
from backend.storage import digest, file_chunks, put_file, read_file, remove_file, store_bytes

log = logging.getLogger('dean')


def types_from(db):
    return {r.id: r.config for r in db.scalars(select(DocumentType))}


def rules_from(db):
    result = {}
    for record in db.scalars(select(Knowledge).order_by(Knowledge.created_at)):
        for key, value in parse_rules(record.text).items():
            if key in result:
                raise ValueError(f'Неоднозначный пункт {key}')
            result[key] = value
    return result


def purge_conversation(db, conversation):
    for row in db.scalars(select(Document).where(Document.conversation_id == conversation.id)):
        remove_file(row.file_key)
    for row in db.scalars(select(Generated).where(Generated.conversation_id == conversation.id)):
        remove_file(row.file_key)
    for model in (Message, Document, Generated):
        db.execute(delete(model).where(model.conversation_id == conversation.id))
    db.delete(conversation)


def cleanup():
    with Session() as db:
        for row in db.scalars(select(Conversation).where(Conversation.expires_at <= now())):
            purge_conversation(db, row)
        db.execute(delete(LoginSession).where(LoginSession.expires <= now()))
        db.execute(delete(AccountToken).where(AccountToken.expires <= now()))
        db.execute(delete(Audit).where(Audit.created_at < now() - timedelta(days=14)))
        db.commit()


async def process_document(document_id):
    with Session() as db:
        doc = db.get(Document, document_id)
        if not doc or doc.state != 'queued':
            return
        doc.state = 'processing'
        db.commit()
        try:
            content = await asyncio.to_thread(read_file, doc.file_key)
            kind, text, fields = await ai.extract(content, doc.mime, types_from(db), doc.document_type)
            # Re-fetch: it may have been erased while inference was in progress.
            db.expire_all()
            doc = db.get(Document, document_id)
            if not doc:
                return
            doc.document_type, doc.text, doc.fields = kind, text, fields
            doc.validation = validate_fields(fields, types_from(db)[kind])
            doc.state, doc.error = 'ready', ''
            metric(db, 'documents')
            db.commit()
        except Exception:
            log.exception('Document processing failed: %s', document_id)
            db.rollback()
            doc = db.get(Document, document_id)
            if doc:
                doc.state = 'error'
                doc.error = 'Не удалось распознать документ. Проверьте Ollama и модель или передайте обращение деканату.'
                db.commit()


async def process_message(message_id):
    with Session() as db:
        message = db.get(Message, message_id)
        if not message or not message.result.get('pending'):
            return
        conv = db.get(Conversation, message.conversation_id)
        if not conv or conv.status != 'bot':
            message.result = {'pending': False}
            db.commit()
            return
        docs = list(db.scalars(select(Document).where(Document.conversation_id == conv.id).order_by(Document.created_at)))
        if any(d.state in ('queued', 'processing') for d in docs):
            return
        doc = docs[-1] if docs and docs[-1].state == 'ready' else None
        if docs and not doc:
            result = {'answerable': False, 'value': None, 'sources': [], 'quotes': [],
                      'answer': 'Документ не распознан. Повторите обработку или обратитесь в деканат.'}
        else:
            try:
                result = await ai.answer(message.text, doc.fields if doc else {},
                                         types_from(db).get(doc.document_type) if doc else None,
                                         rules_from(db))
            except Exception:
                log.exception('Answer processing failed: %s', message_id)
                result = {'answerable': False, 'value': None, 'sources': [], 'quotes': [],
                          'answer': 'Сейчас помощник недоступен. Проверьте Ollama или передайте вопрос деканату.'}
        db.expire_all()
        message = db.get(Message, message_id)
        conv = db.get(Conversation, conv.id)
        if not message or not conv or conv.status != 'bot':
            return
        message.result = {'pending': False}
        db.add(Message(conversation_id=conv.id, sender='assistant', text=result['answer'],
                       result={**result, 'document_id': doc.id if doc else None, 'question_id': message.id}))
        metric(db, 'bot_answers' if result['answerable'] else 'unanswered')
        db.commit()


async def worker():
    while True:
        try:
            with Session() as db:
                ids = list(db.scalars(select(Document.id).where(Document.state == 'queued').order_by(Document.created_at)))
            if ids:
                await process_document(ids[0])
            with Session() as db:
                pending = [m.id for m in db.scalars(select(Message).where(Message.sender == 'student').order_by(Message.created_at)) if m.result.get('pending')]
            for message_id in pending:
                await process_message(message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Worker iteration failed')
        await asyncio.sleep(1)


async def retention_worker():
    while True:
        try:
            await asyncio.to_thread(cleanup)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Retention cleanup failed')
        await asyncio.sleep(60)


def migrate_account_confirmation(db):
    # Confirmation was removed. Do not change any other access controls.
    for account in db.scalars(select(User).where(User.verified.is_(False))):
        account.verified = True
    db.execute(delete(AccountToken).where(AccountToken.purpose == 'verify'))


@asynccontextmanager
async def lifespan(app):
    check_password(settings().bootstrap_password)
    Base.metadata.create_all(engine)
    with Session() as db:
        migrate_account_confirmation(db)
        if not db.scalar(select(User.id).where(User.role == 'dean', User.active.is_(True))):
            db.add(User(username=settings().bootstrap_username.lower(), name='Сотрудник деканата',
                        email=settings().bootstrap_email, password=hasher.hash(settings().bootstrap_password),
                        role='dean', verified=True, must_change=False))
        if not db.scalar(select(Knowledge.id)):
            db.add(Knowledge(title='Положение · Меридиан · v1.0',
                             text=(ROOT / 'data/case/rules.md').read_text(encoding='utf-8')))
        for key, config in built_in_types().items():
            if not db.get(DocumentType, key):
                db.add(DocumentType(id=key, config=config))
        for doc in db.scalars(select(Document).where(Document.state == 'processing')):
            doc.state = 'queued'
        db.commit()
    task = asyncio.create_task(worker())
    retention = asyncio.create_task(retention_worker())
    yield
    task.cancel()
    retention.cancel()
    await asyncio.gather(task, retention, return_exceptions=True)


app = FastAPI(title='Онлайн-деканат', lifespan=lifespan)


@app.middleware('http')
async def security_headers(request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin not in settings().allowed_origins.split(','):
            return Response('Origin denied', status_code=403)
        if not origin and request.headers.get('sec-fetch-site') == 'cross-site':
            return Response('Origin denied', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    old_password: str
    password: str


class TokenBody(BaseModel):
    token: str
    password: str = ''


class UserCreate(BaseModel):
    username: str = Field(pattern=r'^[a-zA-Z0-9_.-]{3,100}$')
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254)
    password: str
    role: str = Field(pattern='^(student|dean)$')


class TextBody(BaseModel):
    text: str = Field(min_length=1)


def user_json(user):
    return {k: getattr(user, k) for k in ('id', 'username', 'name', 'email', 'role', 'verified', 'must_change', 'active')}


@app.get('/api/health')
def health(db=Depends(get_db)):
    db.execute(select(1))
    return {'status': 'ok'}


@app.get('/api/system')
async def system(user=Depends(ready_user)):
    result = {'database': True, 'ollama': False, 'vision_model': settings().vision_model,
              'answer_model': settings().answer_model, 'models': [], 'retention_days': 14}
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(settings().ollama_url + '/api/tags')
            response.raise_for_status()
            result.update(ollama=True, models=[m['name'] for m in response.json().get('models', [])])
    except (httpx.HTTPError, ValueError):
        pass
    return result


@app.post('/api/auth/login')
def login(body: Login, response: Response, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    if user and user.locked_until and user.locked_until > now():
        raise HTTPException(429, 'Слишком много попыток. Повторите через 15 минут.')
    if not verify(body.password, user.password if user else dummy_hash) or not user or not user.active:
        if user:
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now() + timedelta(minutes=15)
            db.commit()
        raise HTTPException(401, 'Неверный логин или пароль.')
    user.failed_logins, user.locked_until = 0, None
    token = new_session(db, user)
    audit(db, user, 'login')
    db.commit()
    response.set_cookie('session', token, httponly=True, secure=settings().cookie_secure, samesite='strict', max_age=43200)
    return {'token': token, 'user': user_json(user)}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return user_json(user)


@app.post('/api/auth/logout')
def logout(request: Request, response: Response, user=Depends(current_user), db=Depends(get_db)):
    token = request.headers.get('authorization', '').removeprefix('Bearer ') or request.cookies.get('session', '')
    db.execute(delete(LoginSession).where(LoginSession.id == digest(token)))
    db.commit()
    response.delete_cookie('session')
    return {'ok': True}


@app.post('/api/auth/password')
def password(body: PasswordChange, user=Depends(current_user), db=Depends(get_db)):
    if not verify(body.old_password, user.password):
        raise HTTPException(400, 'Текущий пароль неверен.')
    check_password(body.password)
    if body.password == body.old_password:
        raise HTTPException(400, 'Новый пароль должен отличаться от временного.')
    user.password, user.must_change = hasher.hash(body.password), False
    revoke_sessions(db, user)
    audit(db, user, 'password_changed')
    db.commit()
    return {'ok': True, 'login_required': True}


@app.post('/api/auth/forgot')
def forgot(body: dict, tasks: BackgroundTasks, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == str(body.get('username', '')).lower(), User.active.is_(True)))
    if user and settings().smtp_host:
        recent = db.scalar(select(AccountToken).where(AccountToken.user_id == user.id, AccountToken.purpose == 'reset', AccountToken.expires > now() + timedelta(minutes=55)))
        if not recent:
            token = account_token(db, user, 'reset')
            db.commit()
            tasks.add_task(send_code, user, token, 'reset')
    return {'message': 'Если почта настроена и аккаунт найден, код отправлен. Иначе запросите код у деканата.'}


@app.post('/api/auth/reset')
def reset(body: TokenBody, db=Depends(get_db)):
    check_password(body.password)
    user = consume_token(db, body.token, 'reset')
    user.password, user.must_change, user.failed_logins, user.locked_until = hasher.hash(body.password), False, 0, None
    revoke_sessions(db, user)
    db.commit()
    return {'ok': True}


@app.get('/api/users')
def users(user=Depends(dean_user), db=Depends(get_db)):
    return [user_json(u) for u in db.scalars(select(User).order_by(User.created_at))]


@app.post('/api/users')
def create_user(body: UserCreate, user=Depends(dean_user), db=Depends(get_db)):
    check_password(body.password)
    if db.scalar(select(User.id).where(User.username == body.username.lower())):
        raise HTTPException(409, 'Такой логин уже существует.')
    created = User(username=body.username.lower(), name=body.name, email=body.email,
                   password=hasher.hash(body.password), role=body.role, verified=True)
    db.add(created)
    db.flush()
    audit(db, user, 'user_created', created.id)
    db.commit()
    return {'user': user_json(created)}


@app.post('/api/users/{user_id}/code/{purpose}')
def user_code(user_id: str, purpose: str, user=Depends(dean_user), db=Depends(get_db)):
    target = db.get(User, user_id)
    if purpose != 'reset' or not target or not target.active:
        raise HTTPException(404, 'Аккаунт или действие не найдено.')
    token = account_token(db, target, purpose)
    audit(db, user, 'code_' + purpose, target.id)
    db.commit()
    return {'code': token}


@app.post('/api/users/{user_id}/active')
def toggle_user(user_id: str, body: dict, user=Depends(dean_user), db=Depends(get_db)):
    target = db.get(User, user_id)
    if not target or target.id == user.id:
        raise HTTPException(400, 'Нельзя отключить собственный аккаунт.')
    target.active = body.get('active') is True
    revoke_sessions(db, target)
    audit(db, user, 'user_active_changed', target.id)
    db.commit()
    return user_json(target)


@app.delete('/api/account/data')
def erase_own_data(user=Depends(current_user), db=Depends(get_db)):
    for conv in db.scalars(select(Conversation).where(Conversation.user_id == user.id)):
        purge_conversation(db, conv)
    audit(db, user, 'personal_data_erased')
    db.commit()
    return {'ok': True}


@app.delete('/api/account')
def erase_account(user=Depends(current_user), db=Depends(get_db)):
    if user.role == 'dean':
        raise HTTPException(403, 'Для удаления аккаунта сотрудника обратитесь к ответственному деканата.')
    for conv in db.scalars(select(Conversation).where(Conversation.user_id == user.id)):
        purge_conversation(db, conv)
    user.name, user.email, user.username = 'Удалённый аккаунт', '', 'deleted-' + user.id
    user.password, user.active = hasher.hash(uid()), False
    revoke_sessions(db, user)
    db.execute(delete(AccountToken).where(AccountToken.user_id == user.id))
    audit(db, user, 'account_erased')
    db.commit()
    return {'ok': True}


def accessible(db, cid, user):
    conv = db.get(Conversation, cid)
    if not conv or conv.expires_at <= now() or (user.role != 'dean' and conv.user_id != user.id):
        raise HTTPException(404, 'Обращение не найдено.')
    return conv


def conversation_json(db, conv):
    owner = db.get(User, conv.user_id)
    return {'id': conv.id, 'title': conv.title, 'status': conv.status,
            'created_at': conv.created_at.isoformat() + 'Z', 'expires_at': conv.expires_at.isoformat() + 'Z',
            'student_name': owner.name if owner else 'Удалённый аккаунт'}


@app.get('/api/conversations')
def conversations(user=Depends(ready_user), db=Depends(get_db)):
    query = select(Conversation).where(Conversation.expires_at > now()).order_by(Conversation.created_at.desc())
    if user.role != 'dean':
        query = query.where(Conversation.user_id == user.id)
    return [conversation_json(db, c) for c in db.scalars(query)]


@app.post('/api/conversations')
def create_conversation(body: TextBody, user=Depends(ready_user), db=Depends(get_db)):
    conv = Conversation(user_id=user.id, title=body.text[:160], expires_at=now() + timedelta(days=14))
    db.add(conv)
    metric(db, 'created')
    db.commit()
    return conversation_json(db, conv)


@app.get('/api/conversations/{cid}')
def conversation(cid: str, user=Depends(ready_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    result = conversation_json(db, conv)
    result['documents'] = [{k: getattr(d, k) for k in ('id', 'filename', 'document_type', 'state', 'text', 'fields', 'validation', 'error')}
                           for d in db.scalars(select(Document).where(Document.conversation_id == cid).order_by(Document.created_at))]
    configs, rules = types_from(db), rules_from(db)
    for doc in result['documents']:
        doc['report'] = document_report(doc['fields'], configs.get(doc['document_type']), rules, doc['state'])
    result['messages'] = [{'id': m.id, 'sender': m.sender, 'text': m.text, 'result': m.result,
                           'created_at': m.created_at.isoformat() + 'Z'}
                          for m in db.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.created_at))]
    result['generated'] = [{'id': g.id, 'filename': g.filename} for g in db.scalars(select(Generated).where(Generated.conversation_id == cid))]
    return result


@app.delete('/api/conversations/{cid}')
def erase_conversation(cid: str, user=Depends(ready_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    purge_conversation(db, conv)
    audit(db, user, 'conversation_erased', cid)
    db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/handoff')
def handoff(cid: str, user=Depends(ready_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    if conv.status != 'dean':
        conv.status = 'dean'
        db.add(Message(conversation_id=cid, sender='system', text='Обращение передано в деканат. Сотрудник увидит документ и всю переписку.'))
        metric(db, 'handoffs')
    db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/messages')
def message(cid: str, body: TextBody, user=Depends(ready_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    if conv.status in ('resolved', 'rejected'):
        raise HTTPException(409, 'Обращение закрыто. Создайте новое.')
    sender = 'dean' if user.role == 'dean' else 'student'
    if requests_handoff(body.text) and sender == 'student':
        conv.status = 'dean'
        metric(db, 'handoffs')
        db.add(Message(conversation_id=cid, sender='system', text='Вы подключены к очереди деканата. Ожидайте ответа сотрудника.'))
    pending = conv.status == 'bot' and sender == 'student'
    db.add(Message(conversation_id=cid, sender=sender, text=body.text, result={'pending': pending}))
    if sender == 'dean':
        audit(db, user, 'reply_sent', cid)
    db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/review')
def review(cid: str, body: dict, user=Depends(dean_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    decision = body.get('decision')
    if decision not in ('approved', 'rejected') or not str(body.get('comment', '')).strip():
        raise HTTPException(422, 'Укажите решение и комментарий.')
    if conv.status in ('resolved', 'rejected'):
        raise HTTPException(409, 'Обращение уже закрыто.')
    conv.status = 'resolved' if decision == 'approved' else 'rejected'
    db.add(Message(conversation_id=cid, sender='dean', text=body['comment'], result={'decision': decision}))
    metric(db, conv.status)
    audit(db, user, 'review_' + decision, cid)
    db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/documents')
def upload_document(cid: str, file: UploadFile = File(...), document_type: str = Form('auto'), user=Depends(ready_user), db=Depends(get_db)):
    conv = accessible(db, cid, user)
    if conv.status in ('resolved', 'rejected'):
        raise HTTPException(409, 'Обращение закрыто.')
    types = types_from(db)
    if document_type != 'auto' and document_type not in types:
        raise HTTPException(422, 'Неизвестный тип документа.')
    header = file.file.read(16)
    file.file.seek(0)
    mime = ('application/pdf' if header.startswith(b'%PDF-') else 'image/png' if header.startswith(b'\x89PNG\r\n\x1a\n')
            else 'image/jpeg' if header.startswith(b'\xff\xd8\xff') else None)
    if not mime:
        raise HTTPException(422, 'Поддерживаются JPG, PNG и PDF. Проверьте содержимое файла.')
    key = uid()
    put_file(key, file.file)
    doc = Document(conversation_id=cid, filename=Path(file.filename or 'document').name,
                   mime=mime, file_key=key, document_type=document_type)
    db.add(doc)
    db.commit()
    return {'id': doc.id, 'state': doc.state}


@app.post('/api/documents/{did}/retry')
def retry(did: str, user=Depends(ready_user), db=Depends(get_db)):
    doc = db.get(Document, did)
    if not doc:
        raise HTTPException(404)
    conv = accessible(db, doc.conversation_id, user)
    if doc.state != 'error' or conv.status in ('resolved', 'rejected'):
        raise HTTPException(409, 'Повтор доступен для документа с ошибкой в открытом обращении.')
    doc.state, doc.error = 'queued', ''
    db.commit()
    return {'ok': True}


@app.patch('/api/documents/{did}/fields')
def edit_fields(did: str, body: dict, user=Depends(dean_user), db=Depends(get_db)):
    doc = db.get(Document, did)
    if not doc:
        raise HTTPException(404)
    accessible(db, doc.conversation_id, user)
    kind = body.get('document_type', doc.document_type)
    config = types_from(db).get(kind)
    if not config or doc.state in ('processing', 'queued'):
        raise HTTPException(422, 'Выберите известный тип и дождитесь завершения OCR.')
    doc.document_type = kind
    doc.fields = normalize_fields(body.get('fields', {}), config)
    doc.validation = validate_fields(doc.fields, config)
    doc.state, doc.error = 'ready', ''
    audit(db, user, 'fields_edited', did)
    db.add(Message(conversation_id=doc.conversation_id, sender='system',
                   text='Деканат уточнил поля документа. Для актуальной проверки задайте вопрос повторно.'))
    db.commit()
    return {'fields': doc.fields, 'validation': doc.validation}


@app.get('/api/documents/{did}/file')
def download_doc(did: str, user=Depends(ready_user), db=Depends(get_db)):
    doc = db.get(Document, did)
    if not doc:
        raise HTTPException(404)
    accessible(db, doc.conversation_id, user)
    return StreamingResponse(file_chunks(doc.file_key), media_type=doc.mime,
                             headers={'Content-Disposition': f"inline; filename*=UTF-8''{quote(doc.filename)}"})


@app.get('/api/conversations/{cid}/results')
def export_results(cid: str, user=Depends(ready_user), db=Depends(get_db)):
    accessible(db, cid, user)
    docs = db.scalars(select(Document).where(Document.conversation_id == cid, Document.state == 'ready'))
    records = []
    for doc in docs:
        answers = []
        for m in db.scalars(select(Message).where(Message.conversation_id == cid, Message.sender == 'assistant')):
            if m.result.get('document_id') == doc.id:
                answers.append({k: m.result[k] for k in ('question_id', 'answerable', 'value', 'answer', 'sources')})
        records.append({'document_id': doc.id, 'document_type': doc.document_type,
                        'fields': doc.fields, 'validation': doc.validation, 'answers': answers})
    return Response(json.dumps({'version': '1.0', 'documents': records}, ensure_ascii=False, indent=2),
                    media_type='application/json', headers={'Content-Disposition': 'attachment; filename=results.json'})


@app.get('/api/types')
def get_types(user=Depends(ready_user), db=Depends(get_db)):
    return types_from(db)


@app.put('/api/types/{tid}')
def put_type(tid: str, body: dict, user=Depends(dean_user), db=Depends(get_db)):
    if not re.fullmatch(r'[a-z][a-z0-9_]{2,99}', tid) or not body.get('title') or not body.get('fields'):
        raise HTTPException(422, 'Нужны идентификатор, название и поля типа.')
    rules = rules_from(db)
    keys = []
    for spec in body['fields']:
        if not isinstance(spec, dict) or not re.fullmatch(r'[a-z][a-z_]+', str(spec.get('key', ''))) or spec.get('kind') not in ('string', 'boolean') or not spec.get('label') or spec.get('rule') not in rules:
            raise HTTPException(422, 'Полю нужны key, label, kind (string/boolean) и существующий пункт rule.')
        keys.append(spec['key'])
    if len(set(keys)) != len(keys):
        raise HTTPException(422, 'Ключи полей должны быть уникальны.')
    if tid in built_in_types() and body != built_in_types()[tid]:
        raise HTTPException(422, 'Базовые схемы кейса фиксированы. Добавьте отдельный тип.')
    record = db.get(DocumentType, tid)
    if record:
        record.config = body
    else:
        db.add(DocumentType(id=tid, config=body))
    audit(db, user, 'type_saved', tid)
    db.commit()
    return {'ok': True}


@app.get('/api/knowledge/search')
def search_knowledge(q: str = Query('', max_length=300), document_id: str | None = None,
                     user=Depends(ready_user), db=Depends(get_db)):
    records = list(db.scalars(select(Knowledge).order_by(Knowledge.created_at)))
    if document_id:
        records = [k for k in records if k.id == document_id]
    clauses, owners = {}, {}
    for record in records:
        for ref, clause_text in parse_rules(record.text).items():
            key = (record.id, ref)
            clauses[key], owners[key] = clause_text, record.title
    # Rank by stable opaque keys; exact clause references are resolved before BM25.
    refs = set(re.findall(r'\b\d+\.\d+\b', q))
    hits = [(key, 1.0) for key in clauses if key[1] in refs] if refs else rank_clauses(q, clauses)
    return {'query':q, 'results':[{'document_id':key[0], 'title':owners[key],
                                  'rule':key[1], 'quote':clauses[key]}
                                 for key, _ in hits[:12]]}


@app.get('/api/knowledge')
def knowledge(user=Depends(ready_user), db=Depends(get_db)):
    return [{'id': k.id, 'title': k.title, 'text': k.text} for k in db.scalars(select(Knowledge).order_by(Knowledge.created_at))]


@app.post('/api/knowledge')
def save_knowledge(body: dict, user=Depends(dean_user), db=Depends(get_db)):
    title, text = str(body.get('title', '')).strip(), str(body.get('text', '')).strip()
    try:
        new_rules = parse_rules(text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not title or not new_rules:
        raise HTTPException(422, 'Нужны название и текст с пунктами вида «7.1. Текст».')
    target = db.get(Knowledge, body.get('id')) if body.get('id') else None
    existing = {}
    for record in db.scalars(select(Knowledge)):
        if not target or record.id != target.id:
            existing.update(parse_rules(record.text))
    if set(existing) & set(new_rules):
        raise HTTPException(422, 'Номера пунктов пересекаются с другими документами.')
    referenced = {f['rule'] for t in types_from(db).values() for f in t['fields']}
    if not referenced.issubset(set(existing) | set(new_rules)):
        raise HTTPException(422, 'Нельзя удалить пункты, на которые ссылаются схемы документов.')
    if target:
        target.title, target.text = title, text
    else:
        target = Knowledge(title=title, text=text)
        db.add(target)
    db.flush()
    audit(db, user, 'knowledge_saved', target.id)
    db.commit()
    return {'id': target.id}


@app.delete('/api/knowledge/{kid}')
def erase_knowledge(kid: str, user=Depends(dean_user), db=Depends(get_db)):
    record = db.get(Knowledge, kid)
    if not record:
        raise HTTPException(404)
    refs = {f['rule'] for t in types_from(db).values() for f in t['fields']}
    if refs & set(parse_rules(record.text)):
        raise HTTPException(422, 'Документ содержит требования, используемые в схемах. Сначала измените схемы.')
    db.delete(record)
    audit(db, user, 'knowledge_deleted', kid)
    db.commit()
    return {'ok': True}


@app.get('/api/templates')
def templates(user=Depends(ready_user), db=Depends(get_db)):
    return [{'id': t.id, 'title': t.title, 'extension': t.extension} for t in db.scalars(select(Template))]


@app.post('/api/templates')
def upload_template(file: UploadFile = File(...), title: str = Form(...), user=Depends(dean_user), db=Depends(get_db)):
    extension = Path(file.filename or '').suffix.lower()
    if extension not in ('.txt', '.md', '.docx'):
        raise HTTPException(422, 'Шаблоны: TXT, Markdown или DOCX с {{ student_name }} и другими ключами полей.')
    key = uid()
    put_file(key, file.file)
    template = Template(title=title, file_key=key, extension=extension)
    db.add(template)
    db.flush()
    audit(db, user, 'template_created', template.id)
    db.commit()
    return {'id': template.id}


@app.delete('/api/templates/{tid}')
def delete_template(tid: str, user=Depends(dean_user), db=Depends(get_db)):
    template = db.get(Template, tid)
    if not template:
        raise HTTPException(404)
    remove_file(template.file_key)
    db.delete(template)
    audit(db, user, 'template_deleted', tid)
    db.commit()
    return {'ok': True}


@app.post('/api/conversations/{cid}/generate/{tid}')
def generate(cid: str, tid: str, user=Depends(dean_user), db=Depends(get_db)):
    accessible(db, cid, user)
    template = db.get(Template, tid)
    doc = db.scalar(select(Document).where(Document.conversation_id == cid, Document.state == 'ready').order_by(Document.created_at.desc()))
    if not template or not doc:
        raise HTTPException(422, 'Нужны шаблон и распознанный документ.')
    from jinja2 import StrictUndefined, meta
    from jinja2.sandbox import SandboxedEnvironment
    content = read_file(template.file_key)
    context = {k: ('есть' if v else 'нет') if isinstance(v, bool) else v for k, v in doc.fields.items()}
    try:
        environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
        if template.extension == '.docx':
            tpl = DocxTemplate(io.BytesIO(content))
            required = tpl.get_undeclared_template_variables()
        else:
            text = content.decode('utf-8-sig')
            required = meta.find_undeclared_variables(environment.parse(text))
        missing = [k for k in required if k not in context or context[k] == MISSING]
        if missing:
            raise HTTPException(422, 'Не хватает данных для шаблона: ' + ', '.join(missing))
        if template.extension == '.docx':
            tpl.render(context, jinja_env=environment, autoescape=True)
            stream = io.BytesIO()
            tpl.save(stream)
            generated = stream.getvalue()
        else:
            generated = environment.from_string(text).render(context).encode('utf-8')
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, 'Шаблон не удалось заполнить. Проверьте ключи {{ field }} и формат.') from exc
    key = uid()
    store_bytes(key, generated)
    record = Generated(conversation_id=cid, filename='document-' + doc.id[:8] + template.extension, file_key=key)
    db.add(record)
    db.flush()
    audit(db, user, 'template_filled', record.id)
    db.add(Message(conversation_id=cid, sender='system', text='Деканат подготовил документ по шаблону. Он доступен для скачивания.'))
    db.commit()
    return {'id': record.id, 'filename': record.filename}


@app.get('/api/generated/{gid}')
def download_generated(gid: str, user=Depends(ready_user), db=Depends(get_db)):
    record = db.get(Generated, gid)
    if not record:
        raise HTTPException(404)
    accessible(db, record.conversation_id, user)
    return StreamingResponse(file_chunks(record.file_key), media_type='application/octet-stream',
                             headers={'Content-Disposition': f"attachment; filename*=UTF-8''{quote(record.filename)}"})


@app.get('/api/stats')
def stats(user=Depends(dean_user), db=Depends(get_db)):
    events = {}
    daily = []
    for m in db.scalars(select(Metric).order_by(Metric.day)):
        events[m.event] = events.get(m.event, 0) + m.count
        daily.append({'day': m.day, 'event': m.event, 'count': m.count})
    queue = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.status == 'dean', Conversation.expires_at > now()))
    return {'events': events, 'daily': daily, 'queue': queue}


@app.get('/api/audit')
def audit_log(user=Depends(dean_user), db=Depends(get_db)):
    return [{'action': a.action, 'actor': a.actor, 'target': a.target, 'created_at': a.created_at.isoformat() + 'Z'}
            for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(500))]


app.mount('/assets', StaticFiles(directory=ROOT / 'web'), name='assets')


@app.get('/')
def index():
    return FileResponse(ROOT / 'web/index.html')
