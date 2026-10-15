"""Exercise actual Qt button signals without changing real accounts."""
import os
import threading
import time
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox

from desktop.main import Desk
from desktop.motion import MotionStack
from PySide6.QtWidgets import QWidget


def test_all_redesigned_pages_render_without_network():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/desktop-design-smoke.py')],
                            cwd=root, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_transitions_can_be_disabled():
    app = QApplication.instance() or QApplication([])
    enabled = [False]
    stack = MotionStack(lambda: enabled[0])
    stack.addWidget(QWidget())
    stack.addWidget(QWidget())
    stack.setCurrentIndex(1)
    assert stack.animation is None
    enabled[0] = True
    stack.setCurrentIndex(0)
    assert stack.animation.duration() == 190
    drain(app, lambda: stack.currentWidget().graphicsEffect() is None)
    enabled[0] = False
    stack.setCurrentIndex(1)
    assert stack.currentWidget().graphicsEffect() is None
    stack.close()


def drain(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition(), 'Qt callback did not reach the GUI event loop'


def test_login_button_enters_workspace_on_gui_thread(monkeypatch):
    app = QApplication.instance() or QApplication([])
    desk = Desk()
    desk.timer.stop()
    main_thread = threading.get_ident()
    callbacks = []
    original_build = desk.build_workspace

    def build():
        callbacks.append(threading.get_ident())
        original_build()

    def request(method, path, **kwargs):
        if path == '/auth/login':
            assert kwargs['json']['username'] == 'dean'
            return {'token': 'fake-test-token', 'user': {
                'role': 'dean', 'name': 'Test dean', 'verified': True, 'must_change': False}}
        return [] if path == '/conversations' else {}

    monkeypatch.setattr(desk, 'request', request)
    monkeypatch.setattr(desk, 'build_workspace', build)
    desk.username.setText(' dean ')
    desk.password.setText('not-a-real-password')
    desk.login_button.click()
    assert not desk.login_button.isEnabled()
    drain(app, lambda: not desk.active_tasks)
    assert callbacks == [main_thread]
    assert desk.stack.currentWidget() == desk.workspace
    assert desk.login_button.isEnabled()
    assert not desk.jobs
    desk.close()


def test_login_failure_shows_error_and_allows_retry(monkeypatch):
    app = QApplication.instance() or QApplication([])
    desk = Desk()
    desk.timer.stop()
    errors = []
    main_thread = threading.get_ident()
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, message:
                        errors.append((message, threading.get_ident())))

    def request(*args, **kwargs):
        raise RuntimeError('Test server unavailable')

    monkeypatch.setattr(desk, 'request', request)
    desk.username.setText('dean')
    desk.password.setText('not-a-real-password')
    for _ in range(2):
        desk.login_button.click()
        drain(app, lambda: not desk.active_tasks)
        assert desk.login_button.isEnabled()
        assert 'login' not in desk.jobs
        assert desk.stack.currentWidget() == desk.login_widget
    assert errors == [('Test server unavailable', main_thread)] * 2
    desk.close()
