"""PDF books with embedded Cyrillic fonts, flowing paragraphs and page numbers."""
from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
import re
import threading

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .text_tools import Book, clean_text, safe_name

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
FONT_LOCK = threading.Lock()
REGULAR = "LoveReadSerif"
BOLD = "LoveReadSerifBold"


def fonts():
    with FONT_LOCK:
        registered = pdfmetrics.getRegisteredFontNames()
        if REGULAR not in registered:
            pdfmetrics.registerFont(TTFont(REGULAR, str(FONT_DIR / "DejaVuSerif.ttf")))
        if BOLD not in registered:
            pdfmetrics.registerFont(TTFont(BOLD, str(FONT_DIR / "DejaVuSerif-Bold.ttf")))


def styles():
    base = dict(fontName=REGULAR, fontSize=11, leading=16.5,
                textColor=colors.HexColor("#252925"), allowWidows=0, allowOrphans=0,
                splitLongWords=1, embeddedHyphenation=0)
    body = ParagraphStyle("BookBody", alignment=TA_JUSTIFY, spaceAfter=7, **base)
    title = ParagraphStyle("BookTitle", parent=body, fontName=BOLD, fontSize=21,
                           leading=28, alignment=TA_LEFT, spaceBefore=8, spaceAfter=15,
                           keepWithNext=True)
    author = ParagraphStyle("BookAuthor", parent=body, fontSize=11.5, leading=17,
                            alignment=TA_LEFT, textColor=colors.HexColor("#666b60"),
                            spaceAfter=24, keepWithNext=True)
    heading = ParagraphStyle("Chapter", parent=body, fontName=BOLD, fontSize=13,
                             leading=19, alignment=TA_LEFT, spaceBefore=15,
                             spaceAfter=10, keepWithNext=True)
    return body, title, author, heading


def paragraph(text, style):
    # The manuscript is always text, never ReportLab's XML-like formatting syntax.
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def paragraphs(text, body, heading):
    result = []
    for block in re.split(r"\n\s*\n", text.strip()):
        if not block:
            continue
        is_heading = len(block) < 130 and re.match(
            r"^(?:(?:глава|розділ|часть|частина)\s+(?:\d+|[IVXLCDM]+)\b|(?:пролог|эпилог|епілог|послесловие|передмова)\s*$)",
            block, re.I)
        result.append(paragraph(block, heading if is_heading else body))
    return result


def draw_page(canvas, doc):
    width, height = A5
    canvas.saveState()
    canvas.setFillColor(colors.HexColor("#73786c"))
    canvas.setFont(REGULAR, 8)
    canvas.drawCentredString(width / 2, 10 * mm, str(doc.page))
    if doc.page > 1:
        title = doc.title
        while title and pdfmetrics.stringWidth(title, REGULAR, 7) > doc.width:
            title = title[:-1]
        if title != doc.title:
            title = title.rstrip()[:-1] + "…"
        canvas.setFont(REGULAR, 7)
        canvas.drawString(doc.leftMargin, height - 11 * mm, title)
    canvas.restoreState()


def write_document(story, title, author, filename, directory):
    fonts()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A5, leftMargin=18 * mm,
                            rightMargin=17 * mm, topMargin=20 * mm,
                            bottomMargin=19 * mm, title=title, author=author,
                            pageCompression=1)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    data = buffer.getvalue()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    base = safe_name(filename)
    index = 1
    while True:
        suffix = "" if index == 1 else f" ({index})"
        target = directory / f"{base}{suffix}.pdf"
        try:
            stream = target.open("xb")
        except FileExistsError:
            index += 1
            continue
        try:
            with stream:
                stream.write(data)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target


def save_book_pdf(book: Book, directory: Path, remove_notes=False, filename=None):
    if not book.chapters or not any(clean_text(c.text, remove_notes) for c in book.chapters):
        raise ValueError("В книге нет текста. Пустой PDF не сохранён.")
    fonts()
    body, title_style, author_style, heading = styles()
    title = clean_text(book.title)
    author = clean_text(book.author)
    story = [paragraph(title, title_style)]
    if author:
        story.append(paragraph(author, author_style))
    else:
        story.append(Spacer(1, 8 * mm))
    for chapter in book.chapters:
        if chapter.title:
            story.append(paragraph(clean_text(chapter.title), heading))
        story.extend(paragraphs(clean_text(chapter.text, remove_notes), body, heading))
    filename = filename or (f"{author} — {title}" if author else title)
    return write_document(story, title, author, filename, directory)


def save_text_pdf(text, filename, directory, heading=None):
    text = clean_text(text)
    if not text:
        raise ValueError("Нет текста для сохранения в PDF.")
    fonts()
    body, title_style, _, chapter_style = styles()
    blocks = re.split(r"\n\s*\n", text)
    story = []
    if heading and blocks[0] == clean_text(heading):
        story.append(paragraph(blocks.pop(0), title_style))
    story.extend(paragraphs("\n\n".join(blocks), body, chapter_style))
    return write_document(story, heading or filename, "", filename, directory)
