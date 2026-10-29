import threading
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
import requests

from gui import backend


def page(body, pages=(), book_id=12):
    links = ''.join(f'<a href="read_book.php?id={book_id}&amp;p={p}">{p}</a>' for p in pages)
    return f'''<html><head><meta charset="utf-8"><title>Читать книгу Тестовая книга - Страница 1</title></head>
    <body><h1>Тестовая книга</h1><a href="biography.php?id=3">Автор</a>
    <div class="textBook">{body}</div><nav>{links}</nav></body></html>'''


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.event = threading.Event()
        self.progress = Mock()
        self.log = Mock()
        pacing = patch.object(backend.upstream, 'PAGE_DELAY', 0)
        pacing.start()
        self.addCleanup(pacing.stop)

    def fetch(self, pages):
        with patch.object(backend, 'get_html', side_effect=pages) as get:
            result = backend.fetch_book('12', self.progress, self.log, self.event)
            return result, get

    def test_accepts_ids_and_canonicalizes_book_links(self):
        expected = 'https://loveread.ec/read_book.php?id=12&p=1'
        for value in ('12', '0012', 'http://www.loveread.ec/view_global.php?id=12',
                      'https://loveread.ec/read_book.php?id=12&p=99', 'loveread.ec/view_global.php?id=12'):
            self.assertEqual(backend.normalize_reference(value), expected)
        for value in ('0', '-1', 'https://example.com/?id=12', 'https://loveread.ec.evil.test/read_book.php?id=12',
                      'https://loveread.ec/read_book.php?id=abc', 'https://loveread.ec/biography.php?id=12',
                      'https://user@loveread.ec/read_book.php?id=12'):
            with self.assertRaises(ValueError):
                backend.normalize_reference(value)

    def test_pagination_ignores_other_books_and_inline_links(self):
        markup = page('<p>Текст <a href="read_book.php?id=12&p=800">ссылка в книге</a></p>', [1, 2, 3])
        markup += '<a href="read_book.php?id=99&p=900">другая книга</a><a href="https://evil.test/read_book.php?id=12&p=1000">не наш сайт</a>'
        self.assertEqual(backend.page_numbers(BeautifulSoup(markup, 'html.parser'), 12), {1, 2, 3})

    def test_extraction_keeps_inline_formatting_and_paragraphs(self):
        soup = BeautifulSoup(page('<p>— «Это <em>важный</em> текст».</p><div class="ads">Реклама</div><script>ads()</script><p>Другой абзац<sup>3</sup>.</p>'), 'html.parser')
        self.assertEqual(backend.extract_page(soup), '— «Это важный текст».\n\nДругой абзац[3].')

    def test_all_pages_in_order_including_short_final_page(self):
        result, get = self.fetch([page('<p>Начало.</p>', [1, 2, 3]), page('<p>Продолжение.</p>', [1, 2, 3]), page('<p>Конец.</p>', [1, 2, 3])])
        self.assertEqual(result.title, 'Тестовая книга')
        self.assertEqual(result.author, 'Автор')
        self.assertEqual([c.text for c in result.chapters], ['Начало.', 'Продолжение.', 'Конец.'])
        self.assertEqual(get.call_count, 3)
        self.assertTrue(get.call_args_list[0].args[0].endswith('p=1'))
        self.assertTrue(get.call_args_list[2].args[0].endswith('p=3'))

    def test_pagination_can_expand_on_later_pages(self):
        result, _ = self.fetch([page('<p>Первый.</p>', [1, 2]), page('<p>Второй.</p>', [1, 2, 3]), page('<p>Третий.</p>', [2, 3])])
        self.assertEqual(len(result.chapters), 3)

    def test_known_duplicate_is_partial_not_success(self):
        with self.assertRaises(backend.PartialBookError) as raised:
            self.fetch([page('<p>Начало.</p>', [1, 2, 3]), page('<p>Начало.</p>', [1, 2, 3])])
        self.assertEqual(raised.exception.expected, 3)
        self.assertEqual(len(raised.exception.book.chapters), 1)

    def test_unknown_pagination_ends_on_duplicate_without_duplication(self):
        one = page('<p>Полный текст.</p>')
        result, get = self.fetch([one, one])
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(get.call_count, 2)

    def test_network_error_mid_book_preserves_partial(self):
        with self.assertRaises(backend.PartialBookError) as raised:
            self.fetch([page('<p>Начало.</p>', [1, 2]), backend.DownloadError('HTTP 403')])
        self.assertIn('страница 2', str(raised.exception))
        self.assertEqual(len(raised.exception.book.chapters), 1)

    def test_missing_text_never_becomes_a_complete_book(self):
        with self.assertRaises(backend.DownloadError):
            self.fetch(['<html><h1>Access denied</h1></html>'])
        with self.assertRaises(backend.PartialBookError):
            self.fetch([page('<p>Начало.</p>'), '<html><h1>Access denied</h1></html>'])

    def test_cancel_before_first_request(self):
        self.event.set()
        with patch.object(backend, 'get_html') as get:
            with self.assertRaises(InterruptedError):
                backend.fetch_book('12', self.progress, self.log, self.event)
            get.assert_not_called()

    def test_404_after_unknown_pagination_ends_the_book(self):
        result, _ = self.fetch([page('<p>Весь текст.</p>'), backend.PageNotFound('404')])
        self.assertEqual(len(result.chapters), 1)

    def test_decode_cp1251_and_stop_on_access_denied(self):
        session = Mock()
        response = Mock(status_code=200, content='<meta charset="windows-1251"><p>Привет!</p>'.encode('cp1251'))
        session.get.return_value = response
        self.assertIn('Привет!', backend.get_html('https://loveread.ec', self.event, self.log, session))
        session.get.return_value = Mock(status_code=403)
        with self.assertRaises(backend.DownloadError):
            backend.get_html('https://loveread.ec', self.event, self.log, session)

    def test_transport_retry_is_interruptible(self):
        session = Mock()
        session.get.side_effect = requests.Timeout('timeout')
        event = Mock()
        event.is_set.return_value = False
        event.wait.return_value = True
        with self.assertRaises(InterruptedError):
            backend.get_html('https://loveread.ec', event, self.log, session)
        self.assertEqual(session.get.call_count, 1)


if __name__ == '__main__':
    unittest.main()
