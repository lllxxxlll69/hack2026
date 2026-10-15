"""Create the native application's multi-resolution Windows icon from its SVG."""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

root = Path(__file__).resolve().parents[1]
app = QApplication.instance() or QApplication([])
renderer = QSvgRenderer(str(root / 'web/brand.svg'))
if not renderer.isValid():
    raise RuntimeError('Invalid application SVG icon')
canvas = QImage(512, 512, QImage.Format_ARGB32)
canvas.fill(Qt.transparent)
painter = QPainter(canvas)
renderer.render(painter)
painter.end()
assets = root / 'assets'
assets.mkdir(exist_ok=True)
preview = assets / 'online-dean.png'
if not canvas.save(str(preview)):
    raise RuntimeError('Could not render application icon')
with Image.open(preview) as source:
    source.save(assets / 'online-dean.ico', format='ICO',
                sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
print('Generated assets/online-dean.ico')
