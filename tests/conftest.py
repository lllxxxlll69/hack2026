import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.fernet import Fernet
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
test_directory = TemporaryDirectory(prefix='online-dean-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(test_directory.name) / 'test.sqlite')
os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
os.environ['BOOTSTRAP_PASSWORD'] = 'TestBootstrap-LongPassword-2026'
os.environ['DATA_DIR'] = test_directory.name
os.environ['SMTP_HOST'] = ''


@pytest.fixture(scope='session', autouse=True)
def close_test_database():
    yield
    from backend.db import engine
    engine.dispose()
    test_directory.cleanup()
