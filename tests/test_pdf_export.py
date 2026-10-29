from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from gui.pdf_export import save_book_pdf, save_text_pdf
from gui.text_tools import Book, Chapter


@unittest.skipUnless(shutil.which('pdftotext') and shutil.which('pdfinfo'), 'Poppler tools required for PDF content checks')
class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def text(path):
        return subprocess.check_output(['pdftotext', str(path), '-'], text=True)

    def test_unicode_metadata_and_authors_punctuation(self):
        book = Book('Українська книга — «Легкість»', 'Автор Ґ. Є. Ї.', chapters=[
            Chapter('Глава 1', '— «Її історія», — відповів він…\n\n2 < 3 & 5 > 4. Текст[12].')])
        path = save_book_pdf(book, self.root)
        self.assertEqual(path.suffix, '.pdf')
        self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
        text = self.text(path)
        for wanted in ('Українська книга', 'Легкість', 'Автор Ґ. Є. Ї.', 'Глава 1', 'Її історія', '2 < 3 & 5 > 4.', '[12]'):
            self.assertIn(wanted, text)
        fonts = subprocess.check_output(['pdffonts', str(path)], text=True)
        self.assertIn('DejaVuSerif', fonts)

    def test_all_paragraphs_survive_across_pages(self):
        body = '\n\n'.join(f'МАРКЕР_{i:04d} — власний тестовий абзац про світло і тишу. ' * 3 for i in range(120))
        book = Book('Довга тестова книга', chapters=[Chapter('', body)])
        path = save_book_pdf(book, self.root)
        extracted = self.text(path)
        for i in range(120):
            self.assertEqual(extracted.count(f'МАРКЕР_{i:04d}'), 3)
        info = subprocess.check_output(['pdfinfo', str(path)], text=True)
        self.assertGreater(int(re.search(r'Pages:\s+(\d+)', info).group(1)), 2)

    def test_one_very_long_paragraph_splits_without_losing_ending(self):
        body = 'ПОЧАТОК_АБЗАЦА ' + 'Довгий абзац без порожніх рядків. ' * 1000 + 'КІНЕЦЬ_АБЗАЦА'
        path = save_text_pdf(body, 'Текст', self.root)
        text = self.text(path)
        self.assertIn('ПОЧАТОК_АБЗАЦА', text)
        self.assertIn('КІНЕЦЬ_АБЗАЦА', text)

    def test_repeat_save_does_not_overwrite_and_notes_are_optional(self):
        book = Book('Книга', chapters=[Chapter('', 'Текст[12].')])
        first = save_book_pdf(book, self.root)
        original = first.read_bytes()
        second = save_book_pdf(book, self.root, remove_notes=True)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original)
        self.assertIn('[12]', self.text(first))
        self.assertNotIn('[12]', self.text(second))

    def test_edited_preview_is_saved_as_text_without_xml_interpretation(self):
        path = save_text_pdf('Назва\n\n<i>Літеральний текст</i> & 1 < 2.', 'Назва', self.root, heading='Назва')
        text = self.text(path)
        self.assertIn('<i>Літеральний текст</i> & 1 < 2.', text)

    def test_no_empty_pdf_on_missing_text(self):
        with self.assertRaises(ValueError):
            save_book_pdf(Book('Пусто'), self.root)
        with self.assertRaises(ValueError):
            save_text_pdf(' \n', 'Пусто', self.root)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
