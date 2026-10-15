from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.config import settings
from backend.storage import SecretJSON, SecretText


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(SecretText)
    email: Mapped[str] = mapped_column(SecretText)
    password: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LoginSession(Base):
    __tablename__ = 'sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires: Mapped[datetime] = mapped_column(DateTime)


class AccountToken(Base):
    __tablename__ = 'account_tokens'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    purpose: Mapped[str] = mapped_column(String(20))
    expires: Mapped[datetime] = mapped_column(DateTime)


class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    title: Mapped[str] = mapped_column(SecretText)
    status: Mapped[str] = mapped_column(String(20), default='bot')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), index=True)
    filename: Mapped[str] = mapped_column(SecretText)
    mime: Mapped[str] = mapped_column(String(100))
    file_key: Mapped[str] = mapped_column(String(36))
    document_type: Mapped[str] = mapped_column(String(100), default='auto')
    state: Mapped[str] = mapped_column(String(20), default='queued')
    text: Mapped[str] = mapped_column(SecretText, default='')
    fields: Mapped[dict] = mapped_column(SecretJSON, default=dict)
    validation: Mapped[dict] = mapped_column(SecretJSON, default=dict)
    error: Mapped[str] = mapped_column(SecretText, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), index=True)
    sender: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(SecretText)
    result: Mapped[dict] = mapped_column(SecretJSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class DocumentType(Base):
    __tablename__ = 'document_types'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    config: Mapped[dict] = mapped_column(SecretJSON)


class Knowledge(Base):
    __tablename__ = 'knowledge'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(SecretText)
    text: Mapped[str] = mapped_column(SecretText)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Template(Base):
    __tablename__ = 'templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(SecretText)
    file_key: Mapped[str] = mapped_column(String(36))
    extension: Mapped[str] = mapped_column(String(10))


class Generated(Base):
    __tablename__ = 'generated'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'))
    filename: Mapped[str] = mapped_column(SecretText)
    file_key: Mapped[str] = mapped_column(String(36))


class Audit(Base):
    __tablename__ = 'audit'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Metric(Base):
    __tablename__ = 'metrics'
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    event: Mapped[str] = mapped_column(String(30), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


engine = create_engine(settings().database_url, pool_pre_ping=True)
Session = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with Session() as db:
        yield db


def audit(db, user, action, target=''):
    db.add(Audit(actor=user.id, action=action, target=target))


def metric(db, event):
    day = now().date().isoformat()
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    statement = insert(Metric).values(day=day, event=event, count=1)
    db.execute(statement.on_conflict_do_update(index_elements=['day', 'event'],
                                               set_={'count': Metric.count + 1}))
