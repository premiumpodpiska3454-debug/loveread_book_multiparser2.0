from pathlib import Path
import tempfile
import unittest

from gui.text_tools import Book, Chapter, book_text, clean_text, html_text, read_text_file, save_book, save_text


class TextTests(unittest.TestCase):
    def test_typography_and_paragraphs_survive(self):
        raw = '\ufeff—  «Привіт!»\u00a0— сказав він…\r\n\r\n\r\nДругий\u200b абзац; 12 + 3 = 15.\u00ad'
        self.assertEqual(clean_text(raw), '— «Привіт!» — сказав він…\n\nДругий абзац; 12 + 3 = 15.')

    def test_footnotes_are_opt_in(self):
        self.assertEqual(clean_text('Текст[12] и [ABC].'), 'Текст[12] и [ABC].')
        self.assertEqual(clean_text('Текст[12] и [ABC].', True), 'Текст и [ABC].')

    def test_entities_controls_and_soft_hyphens(self):
        self.assertEqual(clean_text('A&amp;B\x00\tC\u2060'), 'A&B C')
        self.assertEqual(clean_text('из\u00adдание'), 'издание')
        self.assertEqual(clean_text('2 < 3 & 5 > 4'), '2 < 3 & 5 > 4')

    def test_html_removes_navigation_without_merging_inline_words(self):
        source = '<nav>Меню</nav><h1>Заголовок</h1><p>Это <b>важный</b> текст.</p><p>— Диалог<br>Продолжение</p><script>ads()</script>'
        text = html_text(source)
        self.assertEqual(text, 'Заголовок\n\nЭто важный текст.\n\n— Диалог\nПродолжение')

    def test_safe_utf8_saves_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            book = Book('Название / Тест', 'Автор', chapters=[Chapter('Глава 1', 'Текст\n\n— Диалог.')])
            first = save_book(book, root)
            second = save_book(book, root)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, root)
            self.assertEqual(first.read_text(), book_text(book))
            self.assertNotIn('/', first.name)
            self.assertFalse(first.read_bytes().startswith(b'\xef\xbb\xbf'))
            with self.assertRaises(ValueError):
                save_book(Book('Пусто'), root)
            with self.assertRaises(ValueError):
                save_text(' \n', 'Пусто', root)

    def test_windows_encoding_import(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'test.txt'
            path.write_bytes('Привет, мир!'.encode('cp1251'))
            self.assertEqual(read_text_file(path), 'Привет, мир!')
            path.write_bytes('Українська'.encode('utf-16'))
            self.assertEqual(read_text_file(path), 'Українська')


if __name__ == '__main__':
    unittest.main()
