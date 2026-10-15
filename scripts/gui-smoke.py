"""Offscreen Qt rendering for the app's own widgets (no OS UI automation)."""
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from desktop.main import Desk, STYLE  # noqa: E402
from backend.config import settings  # noqa: E402

app = QApplication([])
if os.name == 'nt':
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeuib.ttf')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/seguisym.ttf')
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
desk = Desk()
desk.timer.stop()
desk.task = lambda fn, callback, key=None: callback(fn())
desk.user = {'name':'Сотрудник деканата', 'verified':True, 'must_change':False}
credentials = {'username':settings().bootstrap_username,'password':settings().bootstrap_password}
data = desk.request('POST', '/auth/login', json=credentials)
desk.token, desk.user = data['token'], data['user']
desk.types = desk.request('GET', '/types')
desk.build_workspace()
desk.render_queue(desk.request('GET', '/conversations'))
if desk.rows:
    desk.cid = desk.rows[0]['id']
    desk.render_detail(desk.request('GET', '/conversations/' + desk.cid))
desk.show()
app.processEvents()
output = ROOT / 'output'
output.mkdir(exist_ok=True)
desk.grab().save(str(output / 'dean-preview.png'))
for index in range(1, 7):
    desk.nav.blockSignals(True)
    desk.nav.setCurrentRow(index)
    desk.nav.blockSignals(False)
    desk.change_page(index)
    app.processEvents()
desk.request('POST', '/auth/logout')
desk.close()
print('Rendered native desktop; all seven pages initialized.')
