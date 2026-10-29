"""Qt desktop UI. Long operations run in a worker, all widgets stay on the UI thread."""
from __future__ import annotations

from pathlib import Path
import re
import sys
import threading

from PySide6.QtCore import QSettings, Qt, QThread, Signal, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from .text_tools import Book, book_text, clean_text, html_text, read_text_file
from .pdf_export import save_book_pdf, save_text_pdf

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path.home() / "Desktop" / "Книги-LoveRead"

STYLE = """
QWidget {font-family:Inter; font-size:13px; color:#e5e7ec;}
QMainWindow, QDialog {background:#11151c;}
QFrame#sidebar {background:#181e27; border:1px solid #28313d; border-radius:18px;}
QFrame#sidebarContents {background:#181e27; border:0;}
QFrame#reader {background:#f4f0e7; border-radius:18px;}
QLabel#eyebrow {color:#c8b78a; font-size:11px; font-weight:700; letter-spacing:2px;}
QLabel#title {font-size:32px; font-weight:700; letter-spacing:-1px;}
QLabel#subtitle, QLabel#muted {color:#97a3b5;}
QLabel#section {font-size:17px; font-weight:600;}
QLabel#readerTitle {color:#30372f; font-size:19px; font-weight:600;}
QLabel#readerMeta {color:#7a8177; font-size:11px;}
QLabel#pill {background:#24372d; color:#b9d8c2; border-radius:10px; padding:6px 12px; font-size:11px;}
QPushButton {background:#252e3b; border:1px solid #354151; border-radius:9px; padding:10px 15px; font-weight:600;}
QPushButton:hover {background:#334154; border-color:#627289;}
QPushButton:pressed {background:#405167;}
QPushButton:disabled {color:#647080; background:#1e2530; border-color:#28303c;}
QPushButton#primary {background:#ccbb90; color:#1c241d; border-color:#ccbb90;}
QPushButton#primary:hover {background:#e6d5ae;}
QPushButton#primary:disabled {background:#504b3f; color:#989383; border-color:#504b3f;}
QPushButton#stop {color:#f0b5a7; border-color:#5f403d; background:#382a2b;}
QPushButton#light {background:#e8e3d8; color:#394337; border-color:#d7d0c2;}
QPushButton#light:hover {background:#d9dfce;}
QPlainTextEdit {background:#10161f; border:1px solid #354151; border-radius:10px; padding:10px; selection-background-color:#516e60;}
QPlainTextEdit:focus {border-color:#bcac83;}
QPlainTextEdit#preview {background:#f4f0e7; color:#30372f; border:0; padding:20px 26px; font-family:'Noto Serif','DejaVu Serif'; font-size:17px; selection-background-color:#c6d3b7;}
QPlainTextEdit#log {font-family:monospace; font-size:11px; color:#aebccc; background:#141b24;}
QListWidget {background:transparent; border:0; outline:0;}
QListWidget::item {padding:13px 10px; margin:3px 0; border-radius:8px; color:#aab7c9;}
QListWidget::item:selected {background:#2d3b39; color:#e1eadc;}
QListWidget::item:hover {background:#242e3c;}
QProgressBar {background:#252e3c; border:0; border-radius:4px; height:8px; text-align:center;}
QProgressBar::chunk {background:#c7b786; border-radius:4px;}
QCheckBox {color:#b2becd; spacing:9px;}
QCheckBox::indicator {width:17px; height:17px; border:1px solid #526070; background:#131922; border-radius:4px;}
QCheckBox::indicator:checked {background:#c8b78a; border-color:#e5d5ad; image:url(none);}
QSplitter::handle {background:transparent; width:18px;}
QScrollBar:vertical {background:transparent; width:9px; margin:3px;}
QScrollBar::handle:vertical {background:#6f7b7660; border-radius:3px; min-height:30px;}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {height:0;}
QToolTip {background:#293341; color:#fff; border:1px solid #637184; padding:6px;}
"""


class Worker(QThread):
    progress = Signal(int, int, str)
    message = Signal(str)
    ready = Signal(int, object, str)
    partial = Signal(int, object, str, str)
    failed = Signal(int, str)
    started_item = Signal(int)

    def __init__(self, jobs, output, remove_notes):
        super().__init__()
        self.jobs = jobs
        self.output = output
        self.remove_notes = remove_notes
        self.stop_event = threading.Event()

    def run(self):
        try:
            from .backend import BOOK_DELAY, PartialBookError, fetch_book
        except ImportError as exc:
            self.message.emit(f"Не удалось подключить парсер: {exc}")
            for row, _ in self.jobs:
                self.failed.emit(row, "Парсер не подключён. Нужны исходники в папке upstream.")
            return
        for job_index, (row, url) in enumerate(self.jobs):
            if self.stop_event.is_set():
                break
            if job_index and self.stop_event.wait(float(BOOK_DELAY)):
                break
            self.started_item.emit(row)
            try:
                book = fetch_book(url, self.progress.emit, self.message.emit, self.stop_event)
                if self.stop_event.is_set():
                    break
                path = save_book_pdf(book, self.output, self.remove_notes)
                self.ready.emit(row, book, str(path))
            except PartialBookError as exc:
                title = f"{exc.book.author} — {exc.book.title}" if exc.book.author else exc.book.title
                label = f"[НЕПОЛНАЯ — {len(exc.book.chapters)}" + (f" из {exc.expected}" if exc.expected else " страниц") + "] " + title
                try:
                    path = save_book_pdf(exc.book, self.output, self.remove_notes, filename=label)
                    self.partial.emit(row, exc.book, str(path), str(exc))
                except Exception as save_error:
                    self.failed.emit(row, f"{exc}. Не удалось сохранить частичный текст: {save_error}")
            except InterruptedError:
                self.message.emit("Загрузка остановлена. Завершённые книги сохранены.")
                break
            except Exception as exc:
                self.failed.emit(row, str(exc))


class Window(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings if settings is not None else QSettings("LocalTools", "LoveReadStudio")
        self.output = Path(self.settings.value("output", str(DEFAULT_OUTPUT)))
        self.worker = None
        self.close_pending = False
        self.current_title = "Книга"
        self.display_title = None
        self.current_path = None
        self.preview_size = 17
        self.results = {}
        self.urls = []
        self.states = []
        self.setWindowTitle("Лист · LoveRead Studio")
        self.setWindowIcon(QIcon(str(ROOT / "gui" / "icon.svg")))
        self.resize(1280, 870)
        self.setMinimumSize(960, 720)
        self.setAcceptDrops(True)
        self.build_ui()

    @staticmethod
    def button(text, action, name=None):
        button = QPushButton(text)
        if name:
            button.setObjectName(name)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(38)
        button.clicked.connect(action)
        return button

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(28, 24, 28, 18)
        layout.setSpacing(18)
        top = QHBoxLayout()
        heading = QVBoxLayout()
        brand = QLabel("ЛИСТ  /  LOVEREAD STUDIO")
        brand.setObjectName("eyebrow")
        heading.addWidget(brand)
        title = QLabel("Только книга. Только текст.")
        title.setObjectName("title")
        heading.addWidget(title)
        subtitle = QLabel("Ссылки → главы → готовый PDF. Абзацы и авторская пунктуация остаются.")
        subtitle.setObjectName("subtitle")
        heading.addWidget(subtitle)
        top.addLayout(heading)
        top.addStretch()
        pill = QLabel("PDF  ·  КНИЖНАЯ ВЁРСТКА")
        pill.setObjectName("pill")
        top.addWidget(pill, alignment=Qt.AlignTop)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        sidebar = QFrame()
        sidebar.setObjectName("sidebarContents")
        sidebar.setMinimumWidth(320)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(18, 18, 18, 12)
        left.setSpacing(9)
        label = QLabel("01  Добавьте книги")
        label.setObjectName("section")
        left.addWidget(label)
        hint = QLabel("Ссылки или ID книг через запятую.")
        hint.setObjectName("muted")
        hint.setWordWrap(False)
        left.addWidget(hint)
        self.links = QPlainTextEdit()
        self.links.setPlaceholderText("2334, 1234\nили ссылка на книгу / страницу чтения…")
        self.links.setFixedHeight(75)
        left.addWidget(self.links)
        row = QHBoxLayout()
        self.add_button = self.button("+ В очередь", self.add_links)
        row.addWidget(self.add_button)
        self.local_button = self.button("Открыть TXT / HTML", self.open_local)
        self.local_button.setToolTip("Можно также перетащить TXT / HTML прямо в окно.")
        row.addWidget(self.local_button)
        left.addLayout(row)
        label = QLabel("02  Очередь загрузки")
        label.setObjectName("section")
        left.addWidget(label)
        self.queue = QListWidget()
        self.queue.setMinimumHeight(70)
        self.queue.currentRowChanged.connect(self.select_result)
        left.addWidget(self.queue, 1)
        row = QHBoxLayout()
        self.remove_button = self.button("Убрать", self.remove_item)
        self.clear_button = self.button("Очистить очередь", self.clear_queue)
        row.addWidget(self.remove_button)
        row.addWidget(self.clear_button)
        left.addLayout(row)
        self.notes = QCheckBox("Убирать ссылки на сноски [1], [2]…")
        self.notes.setToolTip("Необязательно: такие номера могут быть частью книги. По умолчанию сохранены.")
        self.notes.setChecked(self.settings.value("remove_notes", False, type=bool))
        self.folder_label = QLabel()
        self.folder_label.setObjectName("muted")
        self.folder_label.setWordWrap(True)
        row = QHBoxLayout()
        self.output_button = self.button("Папка сохранения", self.choose_output)
        row.addWidget(self.output_button)
        row.addWidget(self.button("Открыть папку", self.open_output))
        output_controls = row
        self.start_button = self.button("Скачать и очистить", self.start, "primary")
        self.stop_button = self.button("Остановить загрузку", self.stop, "stop")
        self.stop_button.setVisible(False)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFrameShape(QFrame.NoFrame)
        sidebar_scroll.setMinimumWidth(355)
        sidebar_scroll.setStyleSheet("QScrollArea {background:transparent; border:0;}")
        sidebar_scroll.setWidget(sidebar)
        sidebar_panel = QFrame()
        sidebar_panel.setObjectName("sidebar")
        panel_layout = QVBoxLayout(sidebar_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.addWidget(sidebar_scroll, 1)
        actions = QWidget()
        action_layout = QVBoxLayout(actions)
        action_layout.setContentsMargins(18, 10, 18, 18)
        action_layout.setSpacing(8)
        action_layout.addWidget(self.notes)
        action_layout.addWidget(self.folder_label)
        action_layout.addLayout(output_controls)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.stop_button)
        panel_layout.addWidget(actions)
        splitter.addWidget(sidebar_panel)

        reader = QFrame()
        reader.setObjectName("reader")
        right = QVBoxLayout(reader)
        right.setContentsMargins(22, 20, 22, 18)
        reader_top = QHBoxLayout()
        reader_label = QLabel("Предпросмотр текста")
        reader_label.setObjectName("readerTitle")
        reader_top.addWidget(reader_label)
        reader_top.addStretch()
        reader_top.addWidget(self.button("−", lambda: self.zoom(-1), "light"))
        reader_top.addWidget(self.button("+", lambda: self.zoom(1), "light"))
        right.addLayout(reader_top)
        meta = QLabel("Текст можно отредактировать перед повторным сохранением.")
        meta.setObjectName("readerMeta")
        right.addWidget(meta)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("preview")
        self.preview.setPlaceholderText("Здесь появится текст книги.\n\nДобавьте ссылку слева или откройте TXT / HTML для очистки.\n\nМы убираем скрытые символы и лишние пробелы, сохраняя смысл, абзацы и знаки препинания.")
        self.preview.textChanged.connect(self.update_count)
        right.addWidget(self.preview, 1)
        bottom = QHBoxLayout()
        self.count = QLabel("0 слов · 0 знаков")
        self.count.setObjectName("readerMeta")
        bottom.addWidget(self.count)
        bottom.addStretch()
        bottom.addWidget(self.button("Очистить текст", self.clean_preview, "light"))
        self.save_button = self.button("Сохранить PDF", self.save_preview, "light")
        bottom.addWidget(self.save_button)
        right.addLayout(bottom)
        splitter.addWidget(reader)
        splitter.setSizes([395, 770])
        layout.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        layout.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = QLabel("Готово к работе. Добавьте первую книгу.")
        self.status.setObjectName("muted")
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status.setMinimumWidth(0)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.button("Журнал", self.show_log))
        layout.addLayout(bottom)
        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle("Журнал загрузки")
        self.log_dialog.resize(800, 450)
        QVBoxLayout(self.log_dialog).addWidget(self.log)
        self.update_folder()
        self.update_count()
        if not (ROOT / "gui" / "backend.py").is_file():
            self.start_button.setEnabled(False)
            self.start_button.setText("Загрузка: ожидаются исходники")
            self.start_button.setToolTip("Нужно склонировать репозиторий в upstream и подключить его парсер. Очистка локальных файлов уже доступна.")
            self.notify("Очистка файлов готова. Для загрузки книг ожидается подключение исходного парсера.")

    def notify(self, text):
        self.status.setText(text)
        self.status.setToolTip(text)
        self.log.appendPlainText(text)

    def update_folder(self):
        self.folder_label.setText(f"Сохраняем в:\n{self.output}")
        self.settings.setValue("output", str(self.output))

    def add_links(self):
        try:
            from .backend import normalize_reference
        except ImportError as exc:
            self.notify(f"Не удалось подключить парсер: {exc}")
            return
        values = [v for v in re.split(r"[\s,;]+", self.links.toPlainText().strip()) if v]
        added = 0
        invalid = []
        for value in values:
            try:
                normalized = normalize_reference(value)
            except ValueError as exc:
                invalid.append(value)
                self.log.appendPlainText(f"{value}: {exc}")
                continue
            if normalized in self.urls:
                continue
            self.urls.append(normalized)
            self.states.append("waiting")
            item = QListWidgetItem("Ожидает  ·  " + value)
            item.setToolTip(normalized)
            self.queue.addItem(item)
            added += 1
        self.links.setPlainText("\n".join(invalid))
        self.notify(f"Добавлено: {added}. В очереди: {len(self.urls)}." + (" Проверьте оставшиеся ссылки." if invalid else ""))

    def remove_item(self):
        row = self.queue.currentRow()
        if row >= 0:
            self.queue.takeItem(row)
            self.urls.pop(row)
            self.states.pop(row)
            self.results = {i if i < row else i - 1: v for i, v in self.results.items() if i != row}

    def clear_queue(self):
        self.queue.clear()
        self.urls.clear()
        self.states.clear()
        self.results.clear()
        self.notify("Очередь очищена. Скачанные файлы сохранены.")

    def choose_output(self):
        selected = QFileDialog.getExistingDirectory(self, "Папка сохранения", str(self.output))
        if selected:
            self.output = Path(selected)
            self.update_folder()

    def open_output(self):
        self.output.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output)))

    def show_log(self):
        self.log_dialog.show()
        self.log_dialog.raise_()

    def start(self):
        if self.links.toPlainText().strip():
            self.add_links()
        jobs = [(i, url) for i, url in enumerate(self.urls) if self.states[i] != "done"]
        if not jobs:
            self.notify("Добавьте ссылку на книгу или откройте локальный файл.")
            return
        self.settings.setValue("remove_notes", self.notes.isChecked())
        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.worker = Worker(jobs, self.output, self.notes.isChecked())
        self.worker.message.connect(self.notify)
        self.worker.progress.connect(self.on_progress)
        self.worker.ready.connect(self.on_ready)
        self.worker.partial.connect(self.on_partial)
        self.worker.failed.connect(self.on_failed)
        self.worker.started_item.connect(self.on_started)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def set_busy(self, busy):
        for widget in (self.add_button, self.local_button, self.remove_button, self.clear_button, self.links, self.notes, self.output_button):
            widget.setEnabled(not busy)
        self.start_button.setVisible(not busy)
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(True)

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
            self.stop_button.setEnabled(False)
            self.notify("Останавливаем загрузку… Дожидаемся завершения текущего запроса.")

    def on_progress(self, completed, total, text):
        self.progress.setRange(0, total if total > 0 else 0)
        self.progress.setValue(completed)
        self.status.setText(text)
        self.status.setToolTip(text)

    def on_started(self, row):
        self.states[row] = "running"
        self.queue.item(row).setText("Загружаем  ·  " + self.urls[row])
        self.queue.setCurrentRow(row)

    def on_ready(self, row, book, path):
        self.states[row] = "done"
        self.results[row] = (book, path)
        self.queue.item(row).setText("Готово  ·  " + book.title)
        self.queue.item(row).setForeground(QColor("#b9d8c2"))
        self.select_result(row)
        self.notify(f"Сохранено: {Path(path).name}")

    def on_failed(self, row, error):
        self.states[row] = "error"
        self.queue.item(row).setText("Ошибка  ·  " + self.urls[row])
        self.queue.item(row).setForeground(QColor("#e6a99a"))
        self.queue.item(row).setToolTip(error)
        self.notify(error)

    def on_partial(self, row, book, path, error):
        self.states[row] = "partial"
        self.results[row] = (book, path)
        self.queue.item(row).setText("Неполная  ·  " + book.title)
        self.queue.item(row).setForeground(QColor("#e3bd7e"))
        self.queue.item(row).setToolTip(error + "\nСохранён частичный текст: " + path)
        self.select_result(row)
        self.notify(f"{error} Частичный текст сохранён с пометкой НЕПОЛНАЯ.")

    def on_finished(self):
        stopped = self.worker.stop_event.is_set()
        for i, state in enumerate(self.states):
            if state == "running":
                self.states[i] = "waiting"
                self.queue.item(i).setText("Остановлено  ·  " + self.urls[i])
        self.set_busy(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if not stopped and all(s == "done" for s in self.states) else 0)
        done = sum(s == "done" for s in self.states)
        errors = sum(s == "error" for s in self.states)
        partial = sum(s == "partial" for s in self.states)
        self.notify(f"{'Остановлено' if stopped else 'Обработка завершена'}. Готово: {done}. Неполных: {partial}. Ошибок: {errors}.")
        self.worker.deleteLater()
        self.worker = None
        if self.close_pending:
            self.close()

    def select_result(self, row):
        if row in self.results:
            book, path = self.results[row]
            self.current_title = Path(path).stem
            self.display_title = book.title
            self.current_path = Path(path)
            self.preview.setPlainText(book_text(book, self.notes.isChecked()))

    def open_local(self, path=None):
        if path is None or isinstance(path, bool):
            path, _ = QFileDialog.getOpenFileName(self, "Открыть текст", str(Path.home() / "Desktop"), "Текст (*.txt *.html *.htm);;Все файлы (*)")
        if not path:
            return
        try:
            path = Path(path)
            content = read_text_file(path)
            text = html_text(content) if path.suffix.lower() in (".html", ".htm") else clean_text(content, self.notes.isChecked())
            self.preview.setPlainText(text)
            self.current_title = path.stem
            self.display_title = None
            self.current_path = None
            self.notify(f"Открыт файл: {path.name}. Проверьте текст и нажмите «Сохранить PDF».")
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось открыть файл", str(exc))

    def clean_preview(self):
        self.preview.setPlainText(clean_text(self.preview.toPlainText(), self.notes.isChecked()))
        self.notify("Текст очищен. Абзацы и авторские знаки препинания сохранены.")

    def save_preview(self):
        try:
            path = save_text_pdf(clean_text(self.preview.toPlainText(), self.notes.isChecked()), self.current_title, self.output, heading=self.display_title)
            self.current_path = path
            self.notify(f"Сохранено: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось сохранить", str(exc))

    def update_count(self):
        text = self.preview.toPlainText()
        self.count.setText(f"{len(text.split()):,} слов · {len(text):,} знаков".replace(",", " "))
        self.save_button.setEnabled(bool(text.strip()))

    def zoom(self, step):
        self.preview_size = max(12, min(30, self.preview_size + step))
        self.preview.setStyleSheet(f"QPlainTextEdit#preview {{font-size:{self.preview_size}px;}}")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not (self.worker and self.worker.isRunning()):
            if any(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in (".txt", ".html", ".htm") for u in event.mimeData().urls()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".txt", ".html", ".htm"):
                self.open_local(url.toLocalFile())
                break

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.close_pending = True
            self.stop()
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LoveRead Studio")
    app.setStyle("Fusion")
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet(STYLE)
    window = Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
