"""Encrypted database values and chunked encrypted files (no plaintext disk copy)."""
import hashlib
import io
import json
import struct
from typing import BinaryIO

from cryptography.fernet import Fernet
from sqlalchemy.types import Text, TypeDecorator

from backend.config import settings


def cipher():
    return Fernet(settings().encryption_key.encode())


class SecretText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return cipher().encrypt(str(value).encode()).decode() if value is not None else None

    def process_result_value(self, value, dialect):
        return cipher().decrypt(value.encode()).decode() if value is not None else None


class SecretJSON(SecretText):
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return super().process_bind_param(json.dumps(value, ensure_ascii=False), dialect) if value is not None else None

    def process_result_value(self, value, dialect):
        text = super().process_result_value(value, dialect)
        return json.loads(text) if text is not None else None


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def put_file(key: str, source: BinaryIO):
    directory = settings().data_dir / 'files'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / key
    try:
        with target.open('wb') as out:
            while chunk := source.read(1024 * 1024):
                encrypted = cipher().encrypt(chunk)
                out.write(struct.pack('>I', len(encrypted)))
                out.write(encrypted)
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def file_chunks(key: str):
    with (settings().data_dir / 'files' / key).open('rb') as source:
        while header := source.read(4):
            length = struct.unpack('>I', header)[0]
            yield cipher().decrypt(source.read(length))


def read_file(key: str) -> bytes:
    return b''.join(file_chunks(key))


def remove_file(key: str):
    (settings().data_dir / 'files' / key).unlink(missing_ok=True)


def store_bytes(key: str, content: bytes):
    put_file(key, io.BytesIO(content))
