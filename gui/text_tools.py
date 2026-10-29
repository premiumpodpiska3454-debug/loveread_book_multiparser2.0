"""Conservative typography cleanup: keep the author's punctuation and paragraphs."""
from __future__ import annotations

from dataclasses import dataclass, field
import html
import re
import unicodedata
from pathlib import Path


@dataclass
class Chapter:
    title: str
    text: str


@dataclass
class Book:
    title: str
    author: str = ""
    source: str = ""
    chapters: list[Chapter] = field(default_factory=list)


def clean_text(value: str, remove_notes: bool = False) -> str:
    text = str(value)
    # Decode only entity syntax, without interpreting plain text as HTML.
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2028", "\n").replace("\u2029", "\n\n").replace("\f", "\n\n")
    text = text.translate(str.maketrans({
        "\ufeff": "", "\u200b": "", "\u2060": "", "\u00ad": "",
        "\u00a0": " ", "\u202f": " ", "\u2007": " ",
    }))
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")
    if remove_notes:
        # Opt-in only: [123] may also be meaningful in the original work.
        text = re.sub(r"\[\d{1,4}\]", "", text)
    text = "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_text(markup: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(markup, "html.parser")
    for node in soup.select("script, style, noscript, nav, footer, form, button, iframe, svg"):
        node.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for node in soup.find_all(["p", "div", "section", "article", "h1", "h2", "h3", "li"]):
        node.insert_before("\n\n")
        node.insert_after("\n\n")
    return clean_text(soup.get_text())


def book_text(book: Book, remove_notes: bool = False) -> str:
    parts = [clean_text(book.title)]
    if book.author:
        parts.append(clean_text(book.author))
    for chapter in book.chapters:
        title = clean_text(chapter.title)
        body = clean_text(chapter.text, remove_notes)
        if title:
            parts.append(title)
        if body:
            parts.append(body)
    return "\n\n".join(p for p in parts if p) + "\n"


def safe_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean_text(title))
    name = re.sub(r"\s+", " ", name).strip(" .") or "Книга"
    return name.encode("utf-8")[:180].decode("utf-8", errors="ignore")


def save_book(book: Book, directory: Path, remove_notes=False) -> Path:
    text = book_text(book, remove_notes)
    if not book.chapters or not any(clean_text(c.text) for c in book.chapters):
        raise ValueError("В книге нет текста. Пустой файл не сохранён.")
    return save_text(text, f"{book.author} — {book.title}" if book.author else book.title, directory)


def save_text(text: str, title: str, directory: Path) -> Path:
    if not text.strip():
        raise ValueError("Нет текста для сохранения.")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    base = safe_name(title)
    target = directory / f"{base}.txt"
    i = 2
    while target.exists():
        target = directory / f"{base} ({i}).txt"
        i += 1
    # Exclusive creation protects earlier downloads, even with simultaneous apps.
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return target


def read_text_file(path: Path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251"):
        try:
            # UTF-16 without a BOM can misread ordinary non-UTF8 bytes.
            if encoding == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("Не удалось определить кодировку текста.")
