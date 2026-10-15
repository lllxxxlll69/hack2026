"""Native Qt desk for dean staff. Student frontend is served by FastAPI."""
import json
import os
import secrets
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot, Qt, qVersion, QSize
from PySide6.QtGui import QIcon, QFontDatabase
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
                              QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                              QListWidget, QListWidgetItem, QFrame, QMainWindow, QMessageBox, QPushButton,
                              QSplitter, QProgressBar, QTableWidget, QTableWidgetItem,
                              QTextEdit, QVBoxLayout, QWidget)
from shiboken6 import isValid
from desktop.theme import STYLE, Panel, IconList, IconTable, icon, icon_label
from desktop.motion import MotionStack, CountLabel

ROOT = Path(__file__).resolve().parents[1]
if getattr(sys, 'frozen', False):
    candidates = [Path(sys.executable).parent, Path.cwd(), *Path(sys.executable).parents]
    ROOT = next((p for p in candidates if (p / 'compose.yaml').is_file()), Path(sys.executable).parent)
load_dotenv(ROOT / '.env')
ASSETS = Path(getattr(sys, '_MEIPASS', ROOT)) / 'web'
STATUS = {'bot':'Помощник', 'dean':'Ожидает сотрудника', 'resolved':'Решено', 'rejected':'Отклонено'}


class Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, Signals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            self.signals.error.emit(str(exc))


class TaskReceiver(QObject):
    """Keep queued callbacks alive and run them exclusively on the GUI thread."""
    def __init__(self, parent, done, error, finished):
        super().__init__(parent)
        self.done_callback, self.error_callback, self.finished_callback = done, error, finished

    @Slot(object)
    def done(self, value):
        try:
            self.done_callback(value)
        except Exception as exc:
            self.error_callback(str(exc))
        finally:
            self.finished_callback()

    @Slot(str)
    def error(self, message):
        try:
            self.error_callback(message)
        finally:
            self.finished_callback()


class Desk(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Онлайн-деканат · Кабинет сотрудника')
        self.setWindowIcon(QIcon(str(ASSETS / 'brand.svg')))
        self.resize(1280, 858)
        self.setMinimumSize(1060, 720)
        self.token = None
        self.user = None
        self.cid = None
        self.detail = None
        self.types = {}
        self.rows = []
        self.jobs = set()
        self.active_tasks = {}
        self.pool = QThreadPool.globalInstance()
        self.motion_enabled = os.getenv('DEAN_REDUCED_MOTION') != '1'
        self.stack = MotionStack(lambda: self.motion_enabled)
        self.setCentralWidget(self.stack)
        self.login_widget = self.build_login()
        self.stack.addWidget(self.login_widget)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_queue)
        self.timer.start(4000)

    def task(self, fn, callback, key=None, settled=None):
        if key and key in self.jobs:
            return
        if key:
            self.jobs.add(key)
        work = Task(fn)

        def done(value):
            if key:
                self.jobs.discard(key)
            callback(value)

        def error(message):
            if key:
                self.jobs.discard(key)
            if key == 'poll':
                self.statusBar().showMessage('Нет соединения с локальным сервером', 4000)
            else:
                QMessageBox.warning(self, 'Онлайн-деканат', message)

        def finished():
            if key:
                self.jobs.discard(key)
            self.active_tasks.pop(work, None)
            receiver.deleteLater()
            if settled:
                settled()

        receiver = TaskReceiver(self, done, error, finished)
        self.active_tasks[work] = receiver
        work.signals.done.connect(receiver.done, Qt.QueuedConnection)
        work.signals.error.connect(receiver.error, Qt.QueuedConnection)
        self.pool.start(work)

    def request(self, method, path, **kwargs):
        headers = {'Authorization': 'Bearer ' + self.token} if self.token else {}
        r = httpx.request(method, self.base_url + '/api' + path, headers=headers,
                         timeout=kwargs.pop('timeout', 60), trust_env=False, **kwargs)
        if not r.is_success:
            try:
                detail = r.json().get('detail')
            except Exception:
                detail = None
            raise RuntimeError(detail if isinstance(detail, str) else f'Сервер вернул ошибку {r.status_code}')
        return r.json() if 'json' in r.headers.get('content-type', '') else r.content

    def button(self, text, handler, primary=False):
        button = QPushButton(text)
        if primary:
            button.setObjectName('primary')
        button.clicked.connect(handler)
        return button

    def build_login(self):
        widget = QWidget()
        outer = QHBoxLayout(widget)
        outer.addStretch()
        panel = Panel(gradient=True)
        panel.setFixedWidth(420)
        panel.setMaximumHeight(600)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(32, 34, 32, 30)
        layout.setSpacing(16)
        header = QHBoxLayout()
        logo = icon_label('cap', 66, '#021823')
        logo.setStyleSheet('background:#b47e5c;border-radius:9px;padding:7px;')
        header.addWidget(logo)
        title = QLabel('Онлайн-деканат')
        title.setStyleSheet('font-size:24px;font-weight:600;')
        header.addWidget(title)
        layout.addLayout(header)
        subtitle = QLabel('Кабинет сотрудника. Все документы и обращения в одном месте')
        subtitle.setObjectName('subtitle')
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        form.setHorizontalSpacing(22)
        self.server = QLineEdit(os.getenv('DEAN_SERVER', 'http://127.0.0.1:8000'))
        self.base_url = self.server.text().rstrip('/')
        self.server.textChanged.connect(lambda value: setattr(self, 'base_url', value.strip().rstrip('/')))
        self.username = QLineEdit()
        self.username.setPlaceholderText('dean')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.returnPressed.connect(self.login)
        for field in (self.server, self.username, self.password):
            field.setObjectName('loginField')
            field.setMinimumHeight(40)
        form.addRow('Сервер', self.server)
        form.addRow('Логин', self.username)
        form.addRow('Пароль', self.password)
        layout.addLayout(form)
        self.login_button = self.button('Войти', self.login, True)
        layout.addWidget(self.login_button)
        self.login_progress = QProgressBar()
        self.login_progress.setRange(0, 0)
        self.login_progress.setTextVisible(False)
        self.login_progress.setFixedHeight(4)
        self.login_progress.hide()
        layout.addWidget(self.login_progress)
        launch = self.button('Запустить локальный API (Docker)', self.start_api)
        launch.setObjectName('outline')
        layout.addWidget(launch)
        layout.addWidget(self.button('Восстановление / смена пароля', self.account_recovery))
        hint = QLabel('Первый аккаунт: логин и пароль из .env.\nСтудентам доступен веб-кабинет по адресу сервера.')
        hint.setObjectName('subtitle')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        outer.addWidget(panel, 0, Qt.AlignVCenter)
        outer.addStretch()
        return widget

    def start_api(self):
        self.statusBar().showMessage('Запускаем Docker Compose…')

        def run():
            if not (ROOT / 'compose.yaml').exists():
                raise RuntimeError('Укажите сервер или запустите Docker Compose из папки проекта. Для установщика API разворачивается отдельно.')
            result = subprocess.run(['docker', 'compose', 'up', '-d', '--build'], cwd=ROOT,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    timeout=600, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            if result.returncode:
                raise RuntimeError('Не удалось запустить API. Запустите Docker Desktop и проверьте .env.\n' + result.stderr[-1600:])
            return True
        self.task(run, lambda _: QMessageBox.information(self, 'Сервер запущен', 'Локальный API запущен. Можно войти в кабинет.'), 'start_api')

    def login(self):
        if 'login' in self.jobs:
            return
        payload = {'username': self.username.text().strip(), 'password': self.password.text()}
        if not payload['username'] or not payload['password']:
            QMessageBox.warning(self, 'Вход', 'Введите логин и пароль.')
            return
        self.base_url = self.server.text().strip().rstrip('/')
        self.login_button.setEnabled(False)
        self.login_button.setText('Входим…')
        self.login_progress.setVisible(self.motion_enabled)
        self.statusBar().showMessage('Подключаемся к серверу…')

        def settled():
            self.login_button.setEnabled(True)
            self.login_button.setText('Войти')
            self.login_progress.hide()
            self.statusBar().clearMessage()

        def loaded(data):
            if data['user']['role'] != 'dean':
                QMessageBox.information(self, 'Кабинет студента', 'Используйте веб-кабинет по адресу сервера.')
                webbrowser.open(self.server.text())
                return
            self.token, self.user = data['token'], data['user']
            self.password.clear()
            if self.user['must_change']:
                self.account_recovery()
                return
            self.build_workspace()
            self.task(lambda: self.request('GET', '/types'), lambda data: setattr(self, 'types', data))
            self.refresh_queue()
        self.task(lambda: self.request('POST', '/auth/login', json=payload, timeout=15), loaded, 'login', settled)

    def build_workspace(self):
        if hasattr(self, 'workspace'):
            self.stack.removeWidget(self.workspace)
            self.workspace.deleteLater()
        self.workspace = QWidget()
        shell = QHBoxLayout(self.workspace)
        shell.setContentsMargins(14, 8, 26, 8)
        shell.setSpacing(53)
        sidebar = Panel()
        sidebar.setFixedWidth(278)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(12, 20, 12, 14)
        left.setSpacing(8)
        header = QHBoxLayout()
        logo = icon_label('cap', 58, '#021823')
        logo.setStyleSheet('background:#b47e5c;border-radius:8px;padding:5px;')
        header.addWidget(logo)
        brand = QLabel('Онлайн деканат\nкабинет сотрудника')
        brand.setStyleSheet('font-size:18px;')
        header.addWidget(brand)
        left.addLayout(header)
        left.addWidget(self.separator())
        profile = QHBoxLayout()
        avatar = QLabel(self.user['name'][:1].upper())
        avatar.setFixedSize(42, 42)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet('background:#87634b;border-radius:21px;font-size:19px;')
        profile.addWidget(avatar)
        name = QLabel(self.user['name'])
        name.setObjectName('profile')
        name.setWordWrap(True)
        profile.addWidget(name, 1)
        left.addLayout(profile)
        left.addWidget(self.separator())
        self.nav = QListWidget()
        self.nav.setObjectName('navigation')
        self.nav.setIconSize(QSize(27, 27))
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        labels = ['Обращения', 'База правил', 'Шаблоны', 'Типы документов',
                  'Аккаунты', 'Статистика', 'Настройки']
        for label, symbol in zip(labels, ['queue', 'rules', 'templates', 'file-check', 'user', 'stats', 'settings']):
            self.nav.addItem(QListWidgetItem(icon(symbol), label))
        self.nav.currentRowChanged.connect(self.change_page)
        left.addWidget(self.nav, 1)
        left.addWidget(self.separator())
        student = self.button('Открыть кабинет студента', lambda: webbrowser.open(self.base_url))
        student.setIcon(icon('cap'))
        student.setIconSize(QSize(27, 27))
        left.addWidget(student)
        left.addWidget(self.separator())
        logout = self.button('Выйти', self.logout)
        logout.setIcon(icon('logout'))
        logout.setIconSize(QSize(26, 26))
        left.addWidget(logout)
        shell.addWidget(sidebar)
        self.pages = MotionStack(lambda: self.motion_enabled)
        shell.addWidget(self.pages, 1)
        self.pages.addWidget(self.build_queue())
        for _ in range(6):
            self.pages.addWidget(QWidget())
        self.stack.addWidget(self.workspace)
        self.stack.setCurrentWidget(self.workspace)
        self.nav.setCurrentRow(0)

    def separator(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet('background:#50616a;')
        return line

    def logout(self):
        def finish(_):
            self.token = self.user = self.cid = self.detail = None
            self.stack.setCurrentWidget(self.login_widget)
        self.task(lambda: self.request('POST', '/auth/logout'), finish)

    def build_queue(self):
        widget, layout = self.page_widget('Обращения студентов', '')
        top = QHBoxLayout()
        top.setSpacing(18)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по имени или обращению')
        self.search.textChanged.connect(lambda: self.render_queue(self.rows))
        self.filter = QComboBox()
        self.filter.addItems(['Все обращения', 'Ожидают сотрудника', 'Помощник', 'Решённые', 'Отклонённые'])
        self.filter.currentIndexChanged.connect(lambda: self.render_queue(self.rows))
        top.addWidget(self.search, 5)
        top.addWidget(self.filter, 1)
        refresh = self.button('↻', self.refresh_queue)
        refresh.setToolTip('Обновить очередь')
        refresh.setAccessibleName('Обновить очередь')
        refresh.setFixedWidth(40)
        top.addWidget(refresh)
        layout.addLayout(top)
        splitter = QSplitter()
        splitter.setHandleWidth(24)
        self.queue_list = IconList('queue')
        self.queue_list.setMinimumWidth(260)
        self.queue_list.currentItemChanged.connect(self.select_conversation)
        splitter.addWidget(self.queue_list)
        right = QWidget()
        body = QVBoxLayout(right)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)
        chat_panel = Panel()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(18, 14, 18, 10)
        self.conversation_title = QLabel('Выберите обращение')
        self.conversation_title.setWordWrap(True)
        self.conversation_title.setStyleSheet('color:#d0a17e;padding:6px;')
        chat_layout.addWidget(self.conversation_title)
        self.chat = QTextEdit()
        self.chat.setObjectName('chat')
        self.chat.setReadOnly(True)
        chat_layout.addWidget(self.chat)
        body.addWidget(chat_panel, 3)
        self.document_list = QComboBox()
        self.document_list.setVisible(False)
        body.addWidget(self.document_list)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addWidget(self.button('Карточка / поля ↓', self.document_card))
        actions.addWidget(self.button('Оригинал ↓', self.download_original))
        actions.addWidget(self.button('JSON ↓', self.export_result, True))
        body.addLayout(actions)
        reply_panel = QWidget()
        reply_panel.setObjectName('replySurface')
        reply_panel.setStyleSheet('QWidget#replySurface{background:#41494e;border-radius:16px;}')
        reply_layout = QVBoxLayout(reply_panel)
        reply_layout.setContentsMargins(10, 8, 10, 8)
        self.reply = QTextEdit()
        self.reply.setPlaceholderText('Ответ студенту или комментарий к решению…')
        self.reply.setStyleSheet('background:transparent;border:0;padding:4px;')
        reply_layout.addWidget(self.reply)
        send_row = QHBoxLayout()
        send_row.addStretch()
        send = self.button('', self.send_reply)
        send.setObjectName('send')
        send.setIcon(icon('send', '#021823'))
        send.setToolTip('Отправить ответ')
        send.setAccessibleName('Отправить ответ')
        send_row.addWidget(send)
        reply_layout.addLayout(send_row)
        reply_panel.setMinimumHeight(140)
        reply_panel.setMaximumHeight(180)
        body.addWidget(reply_panel, 2)
        actions = QHBoxLayout()
        actions.addWidget(self.button('Подтвердить / решить', lambda: self.review('approved')))
        actions.addWidget(self.button('Отклонить', lambda: self.review('rejected')))
        actions.addWidget(self.button('Заполнить шаблон', self.fill_template))
        body.addLayout(actions)
        splitter.addWidget(right)
        splitter.setSizes([320, 550])
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        return widget

    def refresh_queue(self):
        if not self.token or not self.user or self.user['must_change'] or not hasattr(self, 'workspace'):
            return

        def fetch():
            rows = self.request('GET', '/conversations')
            detail = self.request('GET', '/conversations/' + self.cid) if self.cid and any(c['id'] == self.cid for c in rows) else None
            return rows, detail

        def loaded(data):
            if not self.token:
                return
            rows, detail = data
            self.render_queue(rows)
            if detail and detail['id'] == self.cid:
                self.render_detail(detail)
            elif self.cid and not any(c['id'] == self.cid for c in rows):
                self.cid = self.detail = None
                self.chat.clear()
                self.document_list.clear()
        self.task(fetch, loaded, 'poll')

    def render_queue(self, rows):
        self.rows = rows
        if not hasattr(self, 'queue_list'):
            return
        text = self.search.text().lower()
        status = [None, 'dean', 'bot', 'resolved', 'rejected'][self.filter.currentIndex()]
        signature = (str(rows), text, status)
        if getattr(self, '_queue_signature', None) == signature:
            return
        self._queue_signature = signature
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        for row in rows:
            if (status and row['status'] != status) or text not in (row['title'] + row['student_name']).lower():
                continue
            title = row['title'][:32] + ('…' if len(row['title']) > 32 else '')
            self.queue_list.addItem(row['student_name'] + '\n' + title + '\n' + STATUS.get(row['status'], row['status']))
            item = self.queue_list.item(self.queue_list.count() - 1)
            item.setData(Qt.UserRole, row['id'])
            item.setIcon(icon('user'))
            if row['id'] == self.cid:
                self.queue_list.setCurrentItem(item)
        self.queue_list.blockSignals(False)

    def select_conversation(self, item, previous=None):
        if not item:
            return
        cid = item.data(Qt.UserRole)
        self.cid = cid
        self.reply.clear()
        self.task(lambda: self.request('GET', '/conversations/' + cid), lambda data: self.render_detail(data) if self.cid == cid else None)

    def render_detail(self, data):
        import html
        if self.detail == data:
            return
        self.detail = data
        self.conversation_title.setText(data['student_name'] + ' · ' + STATUS.get(data['status'], data['status']))
        parts = []
        for message in data['messages']:
            sender = {'student':'Студент', 'assistant':'Помощник', 'dean':'Деканат', 'system':'Система'}[message['sender']]
            parts.append(f'<p style="color:#cb956d">{sender} · {html.escape(message["created_at"][:16])}</p>')
            parts.append('<p>' + html.escape(message['text']).replace('\n', '<br>') + '</p>')
            for source in message['result'].get('quotes', []):
                parts.append('<p style="color:#ddbc9f">' + html.escape(source['source'] + ': ' + source['quote']) + '</p>')
            parts.append('<hr>')
        self.chat.setHtml(''.join(parts))
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())
        self.document_list.setVisible(bool(data['documents']))
        previous = self.document_list.currentData()
        self.document_list.clear()
        for doc in data['documents']:
            self.document_list.addItem(doc['filename'] + ' · ' + doc['state'], doc['id'])
        if previous:
            self.document_list.setCurrentIndex(max(0, self.document_list.findData(previous)))

    def send_reply(self):
        if not self.cid or not self.reply.toPlainText().strip():
            return
        cid = self.cid
        text = self.reply.toPlainText()
        self.task(lambda: self.request('POST', f'/conversations/{cid}/messages', json={'text':text}), self.reply_saved)

    def reply_saved(self, _):
        self.reply.clear()
        self.refresh_queue()

    def review(self, decision):
        if not self.cid or not self.reply.toPlainText().strip():
            QMessageBox.information(self, 'Комментарий', 'Напишите комментарий к решению в поле ответа.')
            return
        cid, text = self.cid, self.reply.toPlainText()
        self.task(lambda: self.request('POST', f'/conversations/{cid}/review', json={'decision':decision, 'comment':text}), self.reply_saved)

    def selected_document(self):
        return next((d for d in (self.detail or {}).get('documents', []) if d['id'] == self.document_list.currentData()), None)

    def document_card(self):
        doc = self.selected_document()
        if not doc:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Карточка документа · ' + doc['filename'])
        dialog.resize(1080, 800)
        shell = QHBoxLayout(dialog)
        preview = QLabel('Загружаем оригинал…')
        preview.setAlignment(Qt.AlignCenter)
        preview.setMinimumWidth(380)
        shell.addWidget(preview, 1)
        fields_widget = QWidget()
        layout = QVBoxLayout(fields_widget)
        shell.addWidget(fields_widget, 1)

        def show_preview(content):
            if not isValid(preview):
                return
            if content.startswith(b'%PDF'):
                import pymupdf
                with pymupdf.open(stream=content, filetype='pdf') as pdf:
                    content = pdf[0].get_pixmap(matrix=pymupdf.Matrix(1.3, 1.3), alpha=False).tobytes('png')
            pixmap = QPixmap()
            if pixmap.loadFromData(content):
                preview.setPixmap(pixmap.scaled(460, 690, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                preview.setText('Предпросмотр недоступен. Скачайте оригинал.')
        self.task(lambda: self.request('GET', f'/documents/{doc["id"]}/file'), show_preview)
        type_combo = QComboBox()
        for key, config in self.types.items():
            type_combo.addItem(config['title'], key)
        type_combo.setCurrentIndex(max(0, type_combo.findData(doc['document_type'])))
        layout.addWidget(type_combo)
        report = doc.get('report', {})
        if report.get('available'):
            summary = QLabel(f'По сохранённым полям: {report["present_count"]} из {report["required_count"]} обязательных сведений.\n'
                             + report['summary'])
            summary.setWordWrap(True)
            layout.addWidget(summary)
            progress = QProgressBar()
            progress.setRange(0, max(1, report['required_count']))
            progress.setValue(report['present_count'])
            progress.setFormat('Комплектность: %v / %m (не уверенность OCR)')
            layout.addWidget(progress)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Поле', 'Значение'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        specs = []

        def populate():
            specs[:] = self.types.get(type_combo.currentData(), {}).get('fields', [])
            table.setRowCount(len(specs))
            for i, field in enumerate(specs):
                item = QTableWidgetItem(field['label'])
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(i, 0, item)
                value = doc['fields'].get(field['key'], False if field['kind'] == 'boolean' else 'не найдено')
                if field['kind'] == 'boolean':
                    check = QCheckBox('Есть графическая отметка')
                    check.setChecked(value is True)
                    table.setCellWidget(i, 1, check)
                else:
                    table.setItem(i, 1, QTableWidgetItem(str(value)))
            table.resizeRowsToContents()
        type_combo.currentIndexChanged.connect(populate)
        populate()
        layout.addWidget(table)
        source_view = QTextEdit()
        source_view.setReadOnly(True)
        source_view.setMaximumHeight(105)
        source_view.setPlaceholderText('Выберите поле: здесь появится точный пункт Положения.')
        layout.addWidget(source_view)

        def show_source(row, column, previous_row, previous_column):
            if row < 0 or row >= len(specs):
                return
            if type_combo.currentData() != doc['document_type']:
                source_view.setPlainText('Тип изменён. Сохраните поля и откройте карточку заново для актуальных оснований.')
                return
            check = next((c for c in report.get('checks', []) if c['key'] == specs[row]['key']), None)
            if not check:
                source_view.setPlainText('Отчёт пока недоступен. Обновите очередь после завершения обработки.')
                return
            quote = f'Пункт {check["rule"]}: {check["quote"]}' if check['quote'] else 'Для поля нет цитаты в текущей базе правил.'
            source_view.setPlainText(check['label'] + '\n' + quote + '\n' + check['note'])
        table.currentCellChanged.connect(show_source)
        if report.get('available'):
            note = QLabel(report['disclaimer'])
            note.setWordWrap(True)
            note.setObjectName('subtitle')
            layout.addWidget(note)
        ocr = QTextEdit(doc['text'] or doc['error'])
        ocr.setReadOnly(True)
        ocr.setMaximumHeight(160)
        layout.addWidget(QLabel('Распознанный текст / ошибка'))
        layout.addWidget(ocr)

        def save():
            fields = {spec['key']: table.cellWidget(i, 1).isChecked() if spec['kind'] == 'boolean' else table.item(i, 1).text()
                      for i, spec in enumerate(specs)}
            payload = {'document_type': type_combo.currentData(), 'fields': fields}
            self.task(lambda: self.request('PATCH', f'/documents/{doc["id"]}/fields', json=payload),
                      lambda _: (dialog.accept(), self.refresh_queue()))
        layout.addWidget(self.button('Сохранить уточнённые поля', save, True))
        dialog.exec()

    def save_download(self, path, name):
        target, _ = QFileDialog.getSaveFileName(self, 'Сохранить документ', name)
        if not target:
            return

        def save(content):
            if isinstance(content, dict):
                content = json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8')
            Path(target).write_bytes(content)
            self.statusBar().showMessage('Файл сохранён: ' + target, 7000)
        self.task(lambda: self.request('GET', path), save)

    def download_original(self):
        doc = self.selected_document()
        if doc:
            self.save_download('/documents/' + doc['id'] + '/file', doc['filename'])

    def export_result(self):
        if self.cid:
            self.save_download('/conversations/' + self.cid + '/results', 'results.json')

    def replace_page(self, index, widget):
        old = self.pages.widget(index)
        self.pages.removeWidget(old)
        old.deleteLater()
        self.pages.insertWidget(index, widget)
        self.pages.setCurrentIndex(index)
        self.pages.reveal()

    def change_page(self, index):
        def loaded(handler):
            return lambda data: handler(data) if self.token and self.nav.currentRow() == index else None
        if index == 0:
            self.pages.setCurrentIndex(0)
            self.refresh_queue()
        elif index == 1:
            self.task(lambda: self.request('GET', '/knowledge'), loaded(self.knowledge_page))
        elif index == 2:
            self.task(lambda: self.request('GET', '/templates'), loaded(self.templates_page))
        elif index == 3:
            self.task(lambda: self.request('GET', '/types'), loaded(self.types_page))
        elif index == 4:
            self.task(lambda: self.request('GET', '/users'), loaded(self.users_page))
        elif index == 5:
            self.task(lambda: self.request('GET', '/stats'), loaded(self.stats_page))
        elif index == 6:
            self.settings_page()

    def page_widget(self, title, subtitle):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 26, 24, 30)
        layout.setSpacing(6 if subtitle else 18)
        label = QLabel(title)
        label.setObjectName('brand')
        label.setFixedHeight(70)
        layout.addWidget(label)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setObjectName('subtitle')
            hint.setWordWrap(True)
            layout.addWidget(hint)
        return widget, layout

    def knowledge_page(self, records):
        widget, layout = self.page_widget('База правил', '')
        columns = QHBoxLayout()
        columns.setSpacing(24)
        left = QVBoxLayout()
        panel = Panel('rules')
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(280)
        listing_layout = QVBoxLayout(panel)
        listing_layout.setContentsMargins(14, 14, 14, 14)
        listing_layout.addWidget(QLabel('Положения'))
        search = QLineEdit()
        search.setPlaceholderText('Поиск положения')
        listing_layout.addWidget(search)
        listing_layout.addWidget(self.separator())
        listing = QListWidget()
        listing.setStyleSheet('background:transparent;')
        listing.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        listing.setWordWrap(True)
        for record in records:
            item = QListWidgetItem(record['title'])
            item.setData(Qt.UserRole, record['id'])
            listing.addItem(item)
        listing_layout.addWidget(listing, 1)
        left.addWidget(panel, 1)
        right = QVBoxLayout()
        title, text = QLineEdit(), QTextEdit()
        title.setPlaceholderText('Название Положения')
        text.setObjectName('ruleEditor')
        text.setPlaceholderText('7.1. Текст правила…')
        right.addWidget(title)
        right.addWidget(text, 1)
        query_row = QHBoxLayout()
        rule_query = QLineEdit()
        rule_query.setMaxLength(300)
        rule_query.setPlaceholderText('Поиск в пунктах: штамп, автограф или 3.1')
        query_row.addWidget(rule_query, 1)
        search_button = self.button('Найти', lambda: run_search())
        search_button.setIcon(icon('search'))
        query_row.addWidget(search_button)
        right.insertLayout(1, query_row)
        search_results = QTextEdit()
        search_results.setReadOnly(True)
        search_results.setMaximumHeight(170)
        search_results.hide()
        right.addWidget(search_results)

        def selected_id():
            item = listing.currentItem()
            return item.data(Qt.UserRole) if item else None

        def load():
            record = next((r for r in records if r['id'] == selected_id()), {})
            title.setText(record.get('title', ''))
            text.setPlainText(record.get('text', ''))
        listing.currentRowChanged.connect(load)

        def filter_records(value):
            for i in range(listing.count()):
                item = listing.item(i)
                item.setHidden(value.lower() not in item.text().lower())
        search.textChanged.connect(filter_records)

        def run_search():
            query, kid = rule_query.text().strip(), selected_id()
            if not query:
                search_results.hide()
                return
            search_results.show()
            search_results.setPlainText('Ищем пункты…')

            def loaded(data):
                if not isValid(search_results) or rule_query.text().strip() != query or selected_id() != kid:
                    return
                search_results.setPlainText('\n\n'.join(
                    f'{hit["title"]} · пункт {hit["rule"]}\n{hit["quote"]}' for hit in data['results'])
                    or 'Пункты не найдены. Попробуйте другие слова или номер пункта.')
            self.task(lambda: self.request('GET', '/knowledge/search', params={'q':query, **({'document_id':kid} if kid else {})}), loaded)
        rule_query.returnPressed.connect(run_search)
        rule_query.textChanged.connect(lambda value: search_results.hide() if not value.strip() else None)

        def new():
            listing.setCurrentRow(-1)
            title.clear()
            text.clear()
            title.setFocus()

        def import_file():
            path, _ = QFileDialog.getOpenFileName(self, 'Импорт правил', '', 'Текст (*.md *.txt)')
            if path:
                try:
                    text.setPlainText(Path(path).read_text(encoding='utf-8-sig'))
                    title.setText(Path(path).stem)
                except Exception as exc:
                    QMessageBox.warning(self, 'Ошибка файла', str(exc))

        def save():
            payload = {'id':selected_id(), 'title':title.text(), 'text':text.toPlainText()}
            self.task(lambda: self.request('POST', '/knowledge', json=payload), lambda _: self.change_page(1))

        def remove():
            kid = selected_id()
            if kid and QMessageBox.question(self, 'Удалить положение?', title.text()) == QMessageBox.Yes:
                self.task(lambda: self.request('DELETE', '/knowledge/' + kid), lambda _: self.change_page(1))
        left.addWidget(self.button('+ Добавить положение', new))
        actions = QHBoxLayout()
        actions.addWidget(self.button('Импорт TXT / Markdown', import_file))
        actions.addWidget(self.button('Удалить положение', remove))
        actions.addWidget(self.button('Сохранить изменения', save, True))
        right.addLayout(actions)
        columns.addLayout(left, 1)
        columns.addLayout(right, 3)
        layout.addLayout(columns, 1)
        if records:
            listing.setCurrentRow(0)
        self.replace_page(1, widget)

    def templates_page(self, records):
        widget, layout = self.page_widget('Шаблоны документов', '')
        panel = Panel('templates')
        box = QVBoxLayout(panel)
        box.setContentsMargins(16, 16, 16, 16)
        hint = QLabel('Загрузите DOCX, TXT или Markdown с полями {{ student_name }}, {{ issue_date }} и другими ключами. Заполнение доступно из обращения.')
        hint.setWordWrap(True)
        box.addWidget(hint)
        listing = QListWidget()
        listing.setStyleSheet('background:transparent;')
        for record in records:
            item = QListWidgetItem(icon('templates'), record['title'] + ' · ' + record['extension'])
            item.setData(Qt.UserRole, record['id'])
            listing.addItem(item)
        box.addWidget(listing, 1)
        layout.addWidget(panel, 1)

        def upload():
            path, _ = QFileDialog.getOpenFileName(self, 'Выберите шаблон', '', 'Шаблоны (*.docx *.md *.txt)')
            if not path:
                return
            def run():
                with open(path, 'rb') as stream:
                    return self.request('POST', '/templates', files={'file':(Path(path).name, stream)}, data={'title':Path(path).stem})
            self.task(run, lambda _: self.change_page(2))

        def remove():
            item = listing.currentItem()
            if item and QMessageBox.question(self, 'Удалить шаблон?', item.text()) == QMessageBox.Yes:
                tid = item.data(Qt.UserRole)
                self.task(lambda: self.request('DELETE', '/templates/' + tid), lambda _: self.change_page(2))
        actions = QHBoxLayout()
        actions.setSpacing(24)
        actions.addWidget(self.button('+ Добавить шаблон', upload, True))
        actions.addWidget(self.button('Удалить шаблон', remove))
        layout.addLayout(actions)
        self.replace_page(2, widget)

    def fill_template(self):
        if not self.cid:
            return
        cid = self.cid

        def loaded(records):
            if not records:
                QMessageBox.information(self, 'Нет шаблонов', 'Добавьте шаблон в разделе «Шаблоны».')
                return
            dialog = QDialog(self)
            dialog.setWindowTitle('Заполнить шаблон')
            layout = QVBoxLayout(dialog)
            combo = QComboBox()
            for record in records:
                combo.addItem(record['title'], record['id'])
            layout.addWidget(combo)

            def fill():
                tid = combo.currentData()

                def generated(result):
                    dialog.accept()
                    self.save_download('/generated/' + result['id'], result['filename'])
                    self.refresh_queue()
                self.task(lambda: self.request('POST', f'/conversations/{cid}/generate/{tid}'), generated)
            layout.addWidget(self.button('Заполнить и скачать', fill, True))
            dialog.exec()
        self.task(lambda: self.request('GET', '/templates'), loaded)

    def types_page(self, records):
        self.types = records
        widget, layout = self.page_widget('Типы документов', '')
        row = QHBoxLayout()
        combo = QComboBox()
        combo.addItem('+ Новый тип', '')
        for key, config in records.items():
            combo.addItem(config['title'], key)
        identifier = QLineEdit()
        identifier.setPlaceholderText('Идентификатор: new_certificate')
        row.addWidget(combo, 1)
        row.addWidget(identifier, 3)
        layout.addLayout(row)
        hint = QLabel('Новый тип добавляется без изменения кода. Сначала добавьте требования в базу правил, затем укажите поля и номера пунктов.')
        hint.setWordWrap(True)
        hint.setObjectName('subtitle')
        layout.addWidget(hint)
        panel = Panel('file-check')
        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 16, 14, 16)
        editor = QTextEdit()
        editor.setObjectName('ruleEditor')
        editor.setStyleSheet('background:transparent;')
        box.addWidget(editor)
        layout.addWidget(panel, 1)

        def load():
            key = combo.currentData()
            identifier.setText(key)
            config = records.get(key, {'title':'Новая справка', 'fields':[{'key':'student_name', 'label':'ФИО студента', 'kind':'string', 'required':True, 'rule':'7.1'}]})
            editor.setPlainText(json.dumps(config, ensure_ascii=False, indent=2))
        combo.currentIndexChanged.connect(load)
        load()

        def save():
            try:
                payload = json.loads(editor.toPlainText())
            except ValueError:
                QMessageBox.warning(self, 'Формат JSON', 'Проверьте JSON конфигурации.')
                return
            key = identifier.text().strip()
            self.task(lambda: self.request('PUT', '/types/' + key, json=payload), lambda _: self.change_page(3))
        save_button = self.button('Сохранить тип', save)
        save_button.setObjectName('outline')
        layout.addWidget(save_button)
        self.replace_page(3, widget)

    def users_page(self, records):
        widget, layout = self.page_widget('Аккаунты', 'Деканат выдаёт логин и временный пароль. Подтверждение кодом не требуется.')
        table = IconTable('user', len(records), 4)
        table.setHorizontalHeaderLabels(['Имя', 'Логин', 'Роль', 'Доступ'])
        table.verticalHeader().setDefaultSectionSize(50)
        table.setShowGrid(False)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, record in enumerate(records):
            for j, value in enumerate([record['name'], record['username'], {'dean':'Деканат', 'student':'Студент'}.get(record['role'], record['role']), 'Активен' if record['active'] else 'Отключён']):
                table.setItem(i, j, QTableWidgetItem(value))
        layout.addWidget(table)
        row = QHBoxLayout()
        row.addWidget(self.button('+ Создать аккаунт', self.create_user_dialog, True))

        def selected():
            index = table.currentRow()
            return records[index] if index >= 0 else None

        def code(purpose):
            record = selected()
            if record:
                self.task(lambda: self.request('POST', f'/users/{record["id"]}/code/{purpose}'),
                          lambda value: self.show_code('Одноразовый код · действует 1 час', value['code']))

        def active():
            record = selected()
            if record:
                self.task(lambda: self.request('POST', f'/users/{record["id"]}/active', json={'active':not record['active']}), lambda _: self.change_page(4))
        row.addWidget(self.button('Восстановить пароль', lambda: code('reset')))
        row.addWidget(self.button('Включить / отключить', active))
        layout.addLayout(row)
        self.replace_page(4, widget)

    def show_code(self, title, text):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(620, 220)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Передайте данные владельцу аккаунта. Код одноразовый.'))
        editor = QTextEdit(text)
        editor.setReadOnly(True)
        layout.addWidget(editor)
        layout.addWidget(self.button('Закрыть', dialog.accept))
        dialog.exec()

    def create_user_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Создать аккаунт')
        dialog.resize(500, 440)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        entries = {}
        for key, label in [('name','ФИО'),('username','Логин'),('email','Почта'),('password','Временный пароль')]:
            entries[key] = QLineEdit()
            form.addRow(label, entries[key])
        entries['password'].setText(secrets.token_urlsafe(15))
        role = QComboBox()
        role.addItem('Студент', 'student')
        role.addItem('Сотрудник деканата', 'dean')
        form.addRow('Роль', role)
        layout.addLayout(form)

        def save():
            payload = {key:entry.text() for key, entry in entries.items()}
            payload['role'] = role.currentData()

            def created(result):
                dialog.accept()
                self.show_code('Аккаунт создан', f'Логин: {payload["username"]}\nВременный пароль: {payload["password"]}\nПри первом входе смените временный пароль.')
                self.change_page(4)
            self.task(lambda: self.request('POST', '/users', json=payload), created)
        layout.addWidget(self.button('Создать аккаунт', save, True))
        dialog.exec()

    def stats_page(self, data):
        widget, layout = self.page_widget('Статистика', 'Обезличенные счётчики сохраняются после удаления документов. История конкретных обращений доступна 14 дней.')
        columns = QHBoxLayout()
        columns.setSpacing(40)
        panel = Panel()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(360)
        metrics = QVBoxLayout(panel)
        metrics.setContentsMargins(14, 10, 14, 16)
        labels = {'created':'Всего обращений', 'documents':'Распознано документов', 'bot_answers':'Ответов помощника',
                  'unanswered':'Нет данных для ответа', 'handoffs':'Передано сотруднику', 'resolved':'Решённых вопросов', 'rejected':'Отклонено'}
        values = [(label, data['events'].get(key, 0)) for key, label in labels.items()]
        values.append(('Ожидают ответа сейчас', data['queue']))
        for i, (label, value) in enumerate(values):
            row = QHBoxLayout()
            name, count = QLabel(label), CountLabel(value, self.motion_enabled)
            name.setObjectName('metricLabel')
            count.setObjectName('metricValue')
            count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(name, 1)
            row.addWidget(count)
            metrics.addLayout(row)
            if i < len(values)-1:
                metrics.addWidget(self.separator())
        metrics.addStretch(2)
        columns.addWidget(panel, 2)
        columns.addWidget(Panel('stats', gradient=True), 3)
        layout.addLayout(columns, 1)
        self.replace_page(5, widget)

    def settings_page(self):
        widget, layout = self.page_widget('Настройки', 'Пароли, состояние моделей и журнал действий сотрудников.')
        columns = QHBoxLayout()
        columns.setSpacing(24)
        left = QVBoxLayout()
        system_panel = Panel('settings')
        box = QVBoxLayout(system_panel)
        box.setContentsMargins(20, 14, 20, 14)
        server_label = QLabel('Сервер: ' + self.base_url)
        server_label.setWordWrap(True)
        box.addWidget(server_label)
        box.addWidget(self.separator())
        system = QTextEdit()
        system.setObjectName('ruleEditor')
        system.setStyleSheet('background:transparent;border:0;')
        system.setReadOnly(True)
        box.addWidget(system, 1)
        left.addWidget(system_panel, 1)
        change = self.button('Сменить пароль', self.account_recovery)
        change.setObjectName('outline')
        left.addWidget(change)
        motion = QCheckBox('Анимации интерфейса')
        motion.setChecked(self.motion_enabled)
        motion.toggled.connect(lambda enabled: setattr(self, 'motion_enabled', enabled))
        left.addWidget(motion)
        audit_panel = Panel('settings')
        audit_box = QVBoxLayout(audit_panel)
        audit_box.setContentsMargins(20, 14, 20, 14)
        audit_box.addWidget(QLabel('Журнал действий (14 дней)'))
        audit_box.addWidget(self.separator())
        audit_view = QTextEdit()
        audit_view.setObjectName('ruleEditor')
        audit_view.setStyleSheet('background:transparent;border:0;')
        audit_view.setReadOnly(True)
        audit_box.addWidget(audit_view, 1)
        columns.addLayout(left, 1)
        columns.addWidget(audit_panel, 1)
        layout.addLayout(columns, 1)
        self.task(lambda: self.request('GET', '/system'), lambda data: system.setPlainText(json.dumps(data, ensure_ascii=False, indent=2)) if isValid(system) else None)
        self.task(lambda: self.request('GET', '/audit'), lambda data: audit_view.setPlainText('\n'.join(f'{a["created_at"]} · {a["action"]} · {a["target"]}' for a in data)) if isValid(audit_view) else None)
        self.replace_page(6, widget)

    def account_recovery(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Пароль и безопасность')
        dialog.resize(500, 400)
        layout = QVBoxLayout(dialog)
        code = QLineEdit()
        code.setPlaceholderText('Код из письма / от деканата')
        password = QLineEdit()
        password.setEchoMode(QLineEdit.Password)
        password.setPlaceholderText('Новый пароль (минимум 12 символов)')
        old = QLineEdit()
        old.setEchoMode(QLineEdit.Password)
        old.setPlaceholderText('Текущий пароль (при смене)')
        for field in (code, old, password):
            layout.addWidget(field)

        def confirmed(_):
            dialog.accept()
            self.token = self.user = None
            self.stack.setCurrentWidget(self.login_widget)
            QMessageBox.information(self, 'Готово', 'Пароль изменён. Войдите заново.')

        def reset_password():
            payload = {'token':code.text(), 'password':password.text()}
            self.task(lambda: self.request('POST', '/auth/reset', json=payload), confirmed)

        def change_password():
            payload = {'old_password':old.text(), 'password':password.text()}
            self.task(lambda: self.request('POST', '/auth/password', json=payload), confirmed)
        layout.addWidget(self.button('Восстановить пароль кодом', reset_password))
        layout.addWidget(self.button('Сменить текущий / временный пароль', change_password, True))
        dialog.exec()


def main():
    testing = '--self-test-output' in sys.argv
    if testing:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    app = QApplication(sys.argv)
    if testing and os.name == 'nt':
        font_directory = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisym.ttf'):
            QFontDatabase.addApplicationFont(str(font_directory / font))
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    desk = Desk()
    desk.show()
    if testing:
        app.processEvents()
        report = Path(sys.argv[sys.argv.index('--self-test-output') + 1]).resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        screenshot = report.with_suffix('.png')
        rendered = desk.grab().save(str(screenshot))
        # Offline end-to-end button test: never log in to or modify real accounts.
        desk.timer.stop()

        def test_request(method, path, **kwargs):
            if path == '/auth/login':
                return {'token': 'self-test-only', 'user': {
                    'role': 'dean', 'name': 'Self-test', 'verified': True, 'must_change': False}}
            return [] if path == '/conversations' else {}

        desk.request = test_request
        desk.username.setText('self-test')
        desk.password.setText('self-test-only')
        desk.login_button.click()
        deadline = time.monotonic() + 5
        while desk.active_tasks and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        login_verified = (hasattr(desk, 'workspace') and desk.stack.currentWidget() == desk.workspace
                          and desk.login_button.isEnabled() and not desk.active_tasks)
        report.write_text(json.dumps({'qt_version':qVersion(), 'window_created':True,
                                     'rendered':rendered, 'login_verified':login_verified,
                                     'frozen':bool(getattr(sys, 'frozen', False))},
                                    indent=2), encoding='utf-8')
        desk.close()
        if not login_verified:
            raise RuntimeError('Desktop login self-test failed')
        return
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
