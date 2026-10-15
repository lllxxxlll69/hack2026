"""UI QA only: isolated SQLite; production always uses PostgreSQL."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
directory = ROOT / 'tmp/ui-qa'
directory.mkdir(parents=True, exist_ok=True)
os.environ['DATABASE_URL'] = 'sqlite:///' + str(directory / 'qa.sqlite')
os.environ['DATA_DIR'] = str(directory)

from backend.db import Base, Session, User, engine  # noqa: E402
from backend.security import hasher  # noqa: E402
from sqlalchemy import select  # noqa: E402
import uvicorn  # noqa: E402

Base.metadata.create_all(engine)
with Session() as db:
    if not db.scalar(select(User).where(User.username == 'student-preview')):
        db.add(User(username='student-preview', name='Тестовый студент', email='preview@example.local',
                    password=hasher.hash('PreviewStudent-2026'), role='student', verified=True, must_change=False))
        db.commit()

if __name__ == '__main__':
    print('UI QA on 127.0.0.1:8000; student-preview / PreviewStudent-2026 (isolated test database).')
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000)
