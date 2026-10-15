"""Render all native screens using explicit offline fixtures, never real accounts."""
import os
import sys
import time
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['DEAN_REDUCED_MOTION'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from desktop.main import Desk, STYLE  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    if os.name == 'nt':
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR']) / 'Fonts' / name))
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    output = ROOT / 'output/native-redesign'
    output.mkdir(parents=True, exist_ok=True)
    warnings = []
    QMessageBox.warning = lambda parent, title, message: warnings.append(message)
    desk = Desk()
    desk.timer.stop()
    desk.show()
    app.processEvents()
    assert desk.grab().save(str(output / 'login.png'))
    user = {'id':'offline-dean', 'name':'Сотрудник деканата', 'username':'dean',
            'role':'dean', 'active':True, 'verified':True, 'must_change':False}
    stamp = '2026-10-15T12:00:00'
    row = {'id':'offline-conversation', 'student_name':'Тестовый студент',
           'title':'Проверка справки об обучении', 'status':'dean', 'created_at':stamp}
    detail = {**row, 'documents':[], 'messages':[
        {'sender':'student', 'text':'Проверьте справку об обучении.', 'created_at':stamp, 'result':{}},
        {'sender':'assistant', 'text':'Демонстрация интерфейса. Обращение передано сотруднику деканата.',
         'created_at':stamp, 'result':{}}]}
    routes = {
        '/types': {'study_certificate':{'title':'Справка об обучении', 'fields':[]}},
        '/conversations':[row], '/conversations/offline-conversation':detail,
        '/knowledge':[{'id':'offline-rule', 'title':'Положение: Меридиан v. 1.0',
                       'text':(ROOT / 'data/case/rules.md').read_text(encoding='utf-8')}],
        '/templates':[], '/users':[user], '/stats':{'events':{}, 'queue':0},
        '/system':{'database':True, 'ollama':False, 'vision_model':'qwen3-vl:2b-instruct',
                   'answer_model':'qwen3-vl:2b-instruct', 'models':[], 'retention_days':14},
        '/audit':[{'created_at':stamp,'action':'offline_design_preview','target':''}],
    }

    def request(method, path, **kwargs):
        assert method == 'GET', 'Design preview must never change accounts or data'
        return routes[path]

    def drain():
        deadline = time.monotonic() + 5
        while desk.active_tasks and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        app.processEvents()
        assert not desk.active_tasks, 'A native callback did not finish'
        assert not warnings, warnings

    desk.request = request
    desk.user, desk.token, desk.types = user, 'offline-only', routes['/types']
    desk.build_workspace()
    drain()
    desk.queue_list.setCurrentRow(0)
    drain()
    for index, name in enumerate(('queue','knowledge','templates','types','accounts','stats','settings')):
        desk.nav.setCurrentRow(index)
        drain()
        assert desk.pages.currentIndex() == index
        assert desk.grab().save(str(output / (name + '.png')))
    # Validate a smaller supported laptop window too.
    desk.resize(1060, 720)
    desk.nav.setCurrentRow(0)
    drain()
    assert desk.grab().save(str(output / 'queue-compact.png'))
    desk.close()
    print('Rendered login + all seven native pages and a compact queue. Offline fixtures only.')


if __name__ == '__main__':
    main()
