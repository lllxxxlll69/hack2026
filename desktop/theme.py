"""Native navy/copper visual system shared across the dean's seven pages."""
import sys
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QListWidget, QTableWidget, QWidget

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'web'
BG, PANEL, ACCENT = '#021823', '#1d2c36', '#b47e5c'
STYLE = '''
QWidget {background:#021823;color:#f5f7f9;font-family:"Segoe UI";font-size:13px;}
QMainWindow,QStackedWidget {background:#021823;}
QLabel {background:transparent;}
QWidget#surface,QWidget#sidebar {background:transparent;}
QLabel#brand {font-size:32px;font-weight:500;color:#fff;padding:6px 8px;}
QLabel#subtitle {color:#c0987b;font-size:12px;padding:0 8px 6px;}
QLabel#sectionTitle {font-size:18px;color:#fff;padding:6px 0;}
QLabel#profile {color:#f4f7f9;padding:15px 0;font-size:13px;}
QLabel#metricValue {color:#c48c65;font-size:16px;}
QLabel#metricLabel {font-size:15px;padding:12px 0;}
QPushButton {background:#1d2c36;border:1px solid transparent;border-radius:17px;padding:9px 15px;min-height:19px;color:#f3f6f8;}
QPushButton:hover {background:#2b404b;border-color:#ad805e;}
QPushButton:pressed {background:#654c3a;}
QPushButton:focus {border:1px solid #dfb18c;}
QPushButton:disabled {color:#8b989e;background:#20313a;}
QPushButton#primary {background:#87634b;border:1px solid #87634b;color:#fff;}
QPushButton#primary:hover {background:#a57957;}
QPushButton#outline {border:1px solid #b47e5c;}
QPushButton#send {background:#b47e5c;border-radius:16px;padding:4px;min-width:23px;min-height:23px;}
QLineEdit,QTextEdit,QComboBox {background:#41494e;border:1px solid transparent;border-radius:12px;padding:10px 13px;selection-background-color:#87634b;selection-color:#fff;}
QLineEdit:focus,QTextEdit:focus,QComboBox:focus {border:1px solid #c28d65;}
QLineEdit#loginField {background:#66686f;border-radius:8px;}
QTextEdit#ruleEditor {color:#d1a282;}
QTextEdit#chat {background:#1d2c36;padding:20px;border:0;}
QComboBox {padding-right:25px;}
QComboBox::drop-down {width:23px;border:0;}
QComboBox QAbstractItemView {background:#1d2c36;selection-background-color:#87634b;}
QListWidget {background:#1d2c36;border:0;border-radius:17px;padding:10px;outline:0;}
QListWidget::item {padding:17px 12px;margin:2px 0;border-radius:14px;}
QListWidget::item:selected {background:#87634b;color:#fff;border:0;}
QListWidget::item:hover {background:#35454d;}
QListWidget#navigation {background:transparent;padding:0;border:0;}
QListWidget#navigation::item {padding:10px 12px;margin:10px 0;border-radius:17px;}
QListWidget#navigation::item:selected {background:#87634b;color:#fff;}
QTableWidget {background:#1d2c36;border:0;border-radius:17px;padding:12px;gridline-color:#46565e;selection-background-color:#87634b;outline:0;}
QTableWidget::item {padding:10px;border-bottom:1px solid #4a5860;}
QHeaderView::section {background:#1d2c36;color:#cb956d;padding:15px 10px;border:0;font-size:15px;}
QHeaderView,QTableCornerButton::section {background:#1d2c36;border:0;}
QScrollBar:vertical {background:#4b4945;width:8px;margin:7px 1px;border-radius:4px;}
QScrollBar::handle:vertical {background:#b0815d;min-height:25px;border-radius:3px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QSplitter::handle {background:#021823;width:20px;}
QCheckBox {padding:6px;background:transparent;}
QDialog {background:#1d2c36;}
QStatusBar {background:#021823;color:#c0987b;}
QToolTip {background:#1d2c36;color:#fff;border:1px solid #b47e5c;padding:8px;}
QProgressBar {background:#344650;border:0;border-radius:3px;text-align:center;}
QProgressBar::chunk {background:#b47e5c;border-radius:3px;}
'''

EXTRA = {
    'user': '<circle cx="12" cy="6" r="4"/><path d="M4 23v-3c0-10 16-10 16 0v3"/>',
    'queue': '<circle cx="9" cy="7" r="5"/><path d="M3 20v-2c0-6 12-6 12 0v2M8 5q3-3 4 0c0 2-3 2-3 4m0 2h.01M16 14h6v8h-9v-6m3 1 2 2 4-5"/>',
    'templates': '<path d="M14 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9Zm0 0v7h7M9 12c-3 0-3 3-1 3m0 3c-2 0-2 3 1 3m6-9c3 0 3 3 1 3m0 3c2 0 2 3-1 3"/>',
    'stats': '<path d="M3 2v20h20M7 17v-5m5 5V9m5 8v-6M5 9l5-5 5 4 7-7"/>',
    'rules': '<path d="M12 5C5 0 2 3 2 3v16s4-3 10 2c6-5 10-2 10-2V3s-3-3-10 2Zm0 0v16M5 10l2 2 3-4m5 2 2 2 3-4"/>',
}


@lru_cache(maxsize=64)
def svg_data(name, color=ACCENT):
    if name in EXTRA:
        view, content = '0 0 24 24', EXTRA[name]
    else:
        root = ET.parse(ASSETS / 'icons.svg').getroot()
        symbol = next((e for e in root if e.get('id') == name), None)
        if symbol is None:
            raise ValueError('Unknown icon: ' + name)
        view = symbol.get('viewBox')
        content = ''.join(ET.tostring(e, encoding='unicode') for e in symbol)
    return QByteArray((f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" fill="none" '
                       f'stroke="{color}" stroke-width="1.3" stroke-linecap="round" '
                       f'stroke-linejoin="round">{content}</svg>').encode())


def icon(name, color=ACCENT, size=26):
    result = QIcon()
    for mode, tint in ((QIcon.Normal, color), (QIcon.Selected, BG)):
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        QSvgRenderer(svg_data(name, tint)).render(painter)
        painter.end()
        pixmap.setDevicePixelRatio(2)
        result.addPixmap(pixmap, mode)
    return result


def icon_label(name, size=48, color=ACCENT):
    label = QLabel()
    label.setFixedSize(size, size)
    label.setPixmap(icon(name, color, size).pixmap(QSize(size, size)))
    label.setAlignment(Qt.AlignCenter)
    return label


class Panel(QWidget):
    def __init__(self, watermark=None, gradient=False):
        super().__init__()
        self.setObjectName('surface')
        self.watermark, self.gradient = watermark, gradient

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        rect = QRectF(self.rect())
        if self.gradient:
            color = QLinearGradient(rect.topLeft(), rect.bottomRight())
            color.setColorAt(0, QColor('#30414a'))
            color.setColorAt(1, QColor(BG))
            painter.setBrush(color)
        else:
            painter.setBrush(QColor(PANEL))
        painter.drawRoundedRect(rect, 20, 20)
        if self.watermark:
            size = min(self.width(), self.height()) * .4
            painter.setOpacity(.12)
            QSvgRenderer(svg_data(self.watermark)).render(
                painter, QRectF((self.width()-size)/2, self.height()*.58-size/2, size, size))


class IconList(QListWidget):
    def __init__(self, watermark=None):
        super().__init__()
        self.watermark = watermark
        self.setIconSize(QSize(26, 26))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.watermark:
            painter = QPainter(self.viewport())
            painter.setOpacity(.09)
            size = min(self.viewport().width(), self.viewport().height()) * .45
            QSvgRenderer(svg_data(self.watermark)).render(painter, QRectF(
                (self.viewport().width()-size)/2, self.viewport().height()*.65-size/2, size, size))


class IconTable(QTableWidget):
    def __init__(self, watermark, rows, columns):
        super().__init__(rows, columns)
        self.watermark = watermark

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setOpacity(.1)
        size = min(self.viewport().width(), self.viewport().height()) * .35
        QSvgRenderer(svg_data(self.watermark)).render(painter, QRectF(
            (self.viewport().width()-size)/2, self.viewport().height()*.6-size/2, size, size))
