"""A fresh clone can generate secrets without pip or changing existing keys."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def test_setup_uses_only_stdlib_and_preserves_existing_env(tmp_path):
    root = Path(__file__).resolve().parents[1]
    scripts = tmp_path / 'scripts'
    scripts.mkdir()
    shutil.copyfile(root / 'scripts/setup.py', scripts / 'setup.py')
    shutil.copyfile(root / '.env.example', tmp_path / '.env.example')
    result = subprocess.run([sys.executable, '-I', '-S', str(scripts / 'setup.py')],
                            capture_output=True, text=True, env=os.environ.copy(), timeout=10)
    assert result.returncode == 0, result.stderr
    env_file = tmp_path / '.env'
    original = env_file.read_bytes()
    values = dict(line.split('=', 1) for line in original.decode().splitlines() if '=' in line and not line.startswith('#'))
    assert len(values['BOOTSTRAP_PASSWORD']) >= 12
    assert len(values['POSTGRES_PASSWORD']) >= 24
    cipher = Fernet(values['ENCRYPTION_KEY'])
    assert cipher.decrypt(cipher.encrypt(b'test')) == b'test'
    second = subprocess.run([sys.executable, '-I', '-S', str(scripts / 'setup.py')],
                            capture_output=True, text=True, timeout=10)
    assert second.returncode == 0
    assert env_file.read_bytes() == original
