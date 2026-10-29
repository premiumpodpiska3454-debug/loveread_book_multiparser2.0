import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from gui import backend
from gui.app import STYLE, Window, Worker
from gui.text_tools import Book, Chapter


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.settings = QSettings(str(self.output / 'test-ui.ini'), QSettings.IniFormat)

    def test_queue_ids_and_links_deduplicate_and_invalid_input_remains(self):
        window = Window(settings=self.settings)
        self.addCleanup(window.close)
        window.links.setPlainText('12, 34\nhttps://loveread.ec/view_global.php?id=12\nwrong')
        window.add_links()
        self.assertEqual(window.queue.count(), 2)
        self.assertEqual(window.links.toPlainText(), 'wrong')
        self.assertTrue(window.start_button.isEnabled())

    def test_open_edit_clean_save_and_zoom(self):
        window = Window(settings=self.settings)
        self.addCleanup(window.close)
        window.output = self.output
        source = self.output / 'Example.txt'
        source.write_text('—  «Текст».\n\nАбзац.', encoding='utf-8')
        window.open_local(source)
        self.assertEqual(window.preview.toPlainText(), '— «Текст».\n\nАбзац.')
        window.preview.appendPlainText('Редакция.')
        window.save_preview()
        result = self.output / 'Example.pdf'
        self.assertEqual(result.read_bytes()[:5], b'%PDF-')
        text = subprocess.check_output(['pdftotext', str(result), '-'], text=True)
        self.assertIn('Редакция.', text)
        self.assertNotIn('Редакция.', source.read_text())
        window.zoom(1)
        self.assertEqual(window.preview.font().pixelSize(), 18)

    def test_worker_saves_complete_book(self):
        worker = Worker([(0, '12')], self.output, False)
        results, errors = [], []
        worker.ready.connect(lambda row, book, path: results.append(path))
        worker.failed.connect(lambda row, text: errors.append(text))
        book = Book('Своя тестовая книга', 'Автор', chapters=[Chapter('', 'Первый абзац.\n\n— Диалог.')])
        with patch.object(backend, 'fetch_book', return_value=book):
            worker.run()
        self.assertFalse(errors)
        self.assertEqual(len(results), 1)
        self.assertEqual(Path(results[0]).suffix, '.pdf')
        text = subprocess.check_output(['pdftotext', results[0], '-'], text=True)
        self.assertIn('Первый абзац.', text)
        self.assertIn('— Диалог.', text)

    def test_partial_book_is_saved_with_clear_filename_and_signal(self):
        worker = Worker([(0, '12')], self.output, False)
        results, complete = [], []
        worker.partial.connect(lambda row, book, path, error: results.append(path))
        worker.ready.connect(lambda *args: complete.append(args))
        book = Book('Длинное название ' * 30, chapters=[Chapter('', 'Текст.')])
        with patch.object(backend, 'fetch_book', side_effect=backend.PartialBookError(book, 'Сбой на странице 2', 5)):
            worker.run()
        self.assertFalse(complete)
        self.assertEqual(len(results), 1)
        self.assertTrue(Path(results[0]).name.startswith('[НЕПОЛНАЯ'))
        self.assertEqual(Path(results[0]).suffix, '.pdf')
        text = subprocess.check_output(['pdftotext', results[0], '-'], text=True)
        self.assertNotIn('[НЕПОЛНАЯ', text)

    def test_worker_cancel_does_not_write_empty_or_fake_success(self):
        worker = Worker([(0, '12')], self.output, False)
        with patch.object(backend, 'fetch_book', side_effect=InterruptedError('cancel')):
            worker.run()
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
