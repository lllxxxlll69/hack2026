import secrets
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete

from backend.config import settings
from backend.db import AccountToken, LoginSession, User, get_db, now
from backend.storage import digest

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def check_password(password):
    if len(password) < 12 or len(password) > 200:
        raise HTTPException(422, 'Пароль должен содержать от 12 до 200 символов.')


def verify(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def current_user(request: Request, db=Depends(get_db)):
    authorization = request.headers.get('authorization', '')
    token = authorization[7:] if authorization.startswith('Bearer ') else request.cookies.get('session')
    session = db.get(LoginSession, digest(token)) if token else None
    user = db.get(User, session.user_id) if session and session.expires > now() else None
    if not user or not user.active:
        raise HTTPException(401, 'Войдите в аккаунт.')
    return user


def ready_user(user=Depends(current_user)):
    if user.must_change:
        raise HTTPException(403, 'Смените временный пароль в настройках.')
    return user


def dean_user(user=Depends(ready_user)):
    if user.role != 'dean':
        raise HTTPException(403, 'Доступно только сотруднику деканата.')
    return user


def new_session(db, user):
    token = secrets.token_urlsafe(48)
    db.add(LoginSession(id=digest(token), user_id=user.id, expires=now() + timedelta(hours=12)))
    return token


def revoke_sessions(db, user):
    db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))


def account_token(db, user, purpose):
    db.execute(delete(AccountToken).where(AccountToken.user_id == user.id, AccountToken.purpose == purpose))
    token = secrets.token_urlsafe(32)
    db.add(AccountToken(id=digest(token), user_id=user.id, purpose=purpose, expires=now() + timedelta(hours=1)))
    return token


def consume_token(db, token, purpose):
    row = db.get(AccountToken, digest(token))
    if not row or row.purpose != purpose or row.expires <= now():
        raise HTTPException(400, 'Код недействителен или истёк.')
    user = db.get(User, row.user_id)
    db.delete(row)
    if not user or not user.active:
        raise HTTPException(400, 'Аккаунт недоступен.')
    return user


def send_code(user, token, purpose):
    config = settings()
    if not config.smtp_host:
        return False
    mail = EmailMessage()
    mail['From'] = config.smtp_from or config.smtp_user
    mail['To'] = user.email
    mail['Subject'] = 'Онлайн-деканат — ' + ('подтверждение аккаунта' if purpose == 'verify' else 'восстановление пароля')
    mail.set_content(f'Ваш одноразовый код (действует 1 час):\n{token}\nВведите его на странице входа в Онлайн-деканат.')
    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=10) as server:
            if config.smtp_starttls:
                server.starttls()
            if config.smtp_user:
                server.login(config.smtp_user, config.smtp_password)
            server.send_message(mail)
        return True
    except (OSError, smtplib.SMTPException):
        return False
