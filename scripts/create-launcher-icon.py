"""Render our vector icon into a multi-resolution Windows ICO and PNG preview."""
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
renderer = QSvgRenderer(str(root / 'assets/docker-launcher.svg'))
if not renderer.isValid():
    raise RuntimeError('Launcher SVG is invalid')
canvas = QImage(1024, 1024, QImage.Format_ARGB32)
canvas.fill(Qt.transparent)
painter = QPainter(canvas)
painter.setRenderHint(QPainter.Antialiasing)
renderer.render(painter)
painter.end()
preview = root / 'assets/docker-launcher.png'
if not canvas.save(str(preview)):
    raise RuntimeError('Could not save launcher preview')
with Image.open(preview) as icon:
    icon.save(root / 'assets/docker-launcher.ico', format='ICO',
              sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
print('Created assets/docker-launcher.ico and assets/docker-launcher.png')
