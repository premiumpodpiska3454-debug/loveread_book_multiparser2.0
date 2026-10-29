import requests
from bs4 import BeautifulSoup
import time
import os
import sys
import re


# ============================================================
# НАСТРОЙКИ
# ============================================================

PAGE_DELAY = 1.5
BOOK_DELAY = 3

# Защита на случай, если сайт не даст определить пагинацию
FALLBACK_MAX_PAGES = 1000

BASE_URL = "https://loveread.ec/read_book.php"


# ============================================================
# КОДИРОВКА ТЕРМИНАЛА
# ============================================================

try:
    sys.stdin.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

except Exception:
    pass


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,"
        "image/avif,image/webp,"
        "*/*;q=0.8"
    ),
    "Accept-Language": (
        "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    ),
    "Connection": "keep-alive"
})


# ============================================================
# БЕЗОПАСНЫЙ ВВОД
# ============================================================

def ask(prompt):

    print(
        prompt,
        end="",
        flush=True
    )

    try:

        data = sys.stdin.buffer.readline()

        return data.decode(
            "utf-8",
            errors="replace"
        ).strip()

    except Exception as e:

        print(
            f"\n❌ Ошибка ввода: {e}"
        )

        return ""


# ============================================================
# ПОЛУЧЕНИЕ HTML
# ============================================================

def get_page_html(url):

    try:

        response = session.get(
            url,
            timeout=15
        )

        response.raise_for_status()

        # Для Loveread обычно UTF-8
        response.encoding = "utf-8"

        return response.text

    except requests.exceptions.RequestException as e:

        print(
            f"\n❌ HTTP ошибка: {e}"
        )

        return None

    except Exception as e:

        print(
            f"\n❌ Ошибка: {e}"
        )

        return None


# ============================================================
# ПОЛУЧЕНИЕ ТЕКСТА
# ============================================================

def extract_text(html):

    if not html:
        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    content = soup.find(
        "div",
        {"class": "textBook"}
    )

    if not content:
        return None

    text = content.get_text(
        separator="\n",
        strip=True
    )

    lines = []

    for line in text.split("\n"):

        line = line.strip()

        if line:
            lines.append(line)

    result = "\n".join(lines)

    if len(result) < 50:
        return None

    return result


# ============================================================
# ПОИСК КОЛИЧЕСТВА СТРАНИЦ
# ============================================================

def find_page_count(book_id):

    print(
        f"\n🔎 Определяю количество страниц "
        f"для ID {book_id}..."
    )

    # --------------------------------------------------------
    # Загружаем первую страницу
    # --------------------------------------------------------

    url = (
        f"{BASE_URL}"
        f"?id={book_id}&p=1"
    )

    html = get_page_html(url)

    if not html:

        print(
            "⚠️ Не удалось получить первую страницу."
        )

        return None

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # --------------------------------------------------------
    # Ищем ссылки вида:
    #
    # ?id=2334&p=47
    #
    # --------------------------------------------------------

    page_numbers = []

    for link in soup.find_all("a"):

        href = link.get("href", "")

        if not href:
            continue

        # Ищем p=число
        matches = re.findall(
            r"(?:[?&])p=(\d+)",
            href
        )

        for match in matches:

            try:

                number = int(match)

                if number > 0:
                    page_numbers.append(number)

            except ValueError:
                pass

    # --------------------------------------------------------
    # Дополнительно ищем числа в HTML,
    # связанные с p=
    # --------------------------------------------------------

    html_matches = re.findall(
        r"(?:[?&])p=(\d+)",
        html
    )

    for match in html_matches:

        try:

            number = int(match)

            if number > 0:
                page_numbers.append(number)

        except ValueError:
            pass

    # --------------------------------------------------------
    # Если нашли пагинацию
    # --------------------------------------------------------

    if page_numbers:

        max_page = max(
            page_numbers
        )

        print(
            f"📄 Найдено страниц: {max_page}"
        )

        return max_page

    # --------------------------------------------------------
    # Попытка найти классическую пагинацию
    # --------------------------------------------------------

    pagination = soup.find(
        class_=re.compile(
            r"page|pagination|navigation",
            re.I
        )
    )

    if pagination:

        numbers = re.findall(
            r"\b\d{1,4}\b",
            pagination.get_text(" ")
        )

        if numbers:

            values = []

            for number in numbers:

                try:

                    value = int(number)

                    if value > 0:
                        values.append(value)

                except ValueError:
                    pass

            if values:

                max_page = max(values)

                print(
                    f"📄 Найдено страниц: {max_page}"
                )

                return max_page

    # --------------------------------------------------------
    # Не удалось определить
    # --------------------------------------------------------

    print(
        "⚠️ Пагинация не найдена."
    )

    print(
        f"⚠️ Использую защитный предел: "
        f"{FALLBACK_MAX_PAGES} страниц."
    )

    return None


# ============================================================
# СКАЧИВАНИЕ КНИГИ
# ============================================================

def download_book(
    book_id,
    output_file
):

    # --------------------------------------------------------
    # Определяем страницы
    # --------------------------------------------------------

    page_count = find_page_count(
        book_id
    )

    if page_count:

        max_pages = page_count

    else:

        max_pages = FALLBACK_MAX_PAGES

    print()

    print("=" * 70)

    print(
        f"📚 КНИГА ID: {book_id}"
    )

    print(
        f"📄 Страниц к загрузке: {max_pages}"
    )

    print(
        f"💾 Файл: {output_file}"
    )

    print("=" * 70)

    all_text = []

    successful = 0

    previous_text = None

    # --------------------------------------------------------
    # Загрузка страниц
    # --------------------------------------------------------

    for page in range(
        1,
        max_pages + 1
    ):

        url = (
            f"{BASE_URL}"
            f"?id={book_id}"
            f"&p={page}"
        )

        print(
            f"[{page:3d}/{max_pages}] "
            f"Загружаю...",
            end=" ",
            flush=True
        )

        html = get_page_html(
            url
        )

        if not html:

            print(
                "❌ Ошибка"
            )

            break

        text = extract_text(
            html
        )

        if not text:

            print(
                "✋ Текст закончился"
            )

            break

        # ----------------------------------------------------
        # Защита от повторяющейся страницы
        # ----------------------------------------------------

        if (
            previous_text is not None
            and text == previous_text
        ):

            print(
                "✋ Повтор страницы"
            )

            break

        # ----------------------------------------------------
        # Добавляем текст
        # ----------------------------------------------------

        all_text.append(
            text
        )

        previous_text = text

        successful += 1

        print(
            "✅"
        )

        time.sleep(
            PAGE_DELAY
        )

    # ========================================================
    # СОХРАНЕНИЕ
    # ========================================================

    if not all_text:

        print()
        print(
            "❌ Текст книги не найден!"
        )

        return False

    try:

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(
                "\n\n".join(
                    all_text
                )
            )

        file_size = (
            os.path.getsize(
                output_file
            ) / 1024
        )

        print()

        print("-" * 70)

        print(
            "✅ КНИГА СКАЧАНА"
        )

        print(
            f"📊 Загружено страниц: "
            f"{successful}"
        )

        print(
            f"💾 Размер: "
            f"{file_size:.2f} KB"
        )

        print(
            f"📁 Файл: "
            f"{output_file}"
        )

        print("-" * 70)

        return True

    except Exception as e:

        print(
            f"\n❌ Ошибка сохранения: {e}"
        )

        return False


# ============================================================
# MAIN
# ============================================================

def main():

    print()

    print("=" * 70)

    print(
        "📚 MULTI BOOK DOWNLOADER"
    )

    print("=" * 70)

    # ========================================================
    # ID
    # ========================================================

    ids_input = ask(
        "\nВведите ID книг через запятую:\n"
        "Например: 2334, 1234, 5678\n\n"
        "ID: "
    )

    if not ids_input:

        print(
            "\n❌ ID не указаны."
        )

        return

    # ========================================================
    # ОБРАБОТКА ID
    # ========================================================

    book_ids = []

    for item in ids_input.split(","):

        item = item.strip()

        item = item.replace(
            " ",
            ""
        )

        if not item:
            continue

        if item.isdigit():

            book_ids.append(
                item
            )

        else:

            print(
                f"⚠️ Пропускаю ID: {item}"
            )

    # Убираем дубликаты
    book_ids = list(
        dict.fromkeys(
            book_ids
        )
    )

    if not book_ids:

        print(
            "\n❌ Нет корректных ID."
        )

        return

    # ========================================================
    # ПАПКА
    # ========================================================

    output_dir = ask(
        "\nВведите путь к папке "
        "для сохранения:\n"
        "Например: /home/sewer64/books\n\n"
        "Путь: "
    )

    if not output_dir:

        print(
            "\n❌ Путь не указан."
        )

        return

    output_dir = os.path.expanduser(
        output_dir
    )

    output_dir = os.path.abspath(
        output_dir
    )

    # ========================================================
    # СОЗДАНИЕ ПАПКИ
    # ========================================================

    try:

        os.makedirs(
            output_dir,
            exist_ok=True
        )

    except Exception as e:

        print(
            f"\n❌ Ошибка создания папки: {e}"
        )

        return

    # ========================================================
    # ИНФОРМАЦИЯ
    # ========================================================

    print()

    print("=" * 70)

    print(
        "⚙️ НАСТРОЙКИ"
    )

    print("=" * 70)

    print(
        f"📚 Книг: {len(book_ids)}"
    )

    print(
        f"🆔 ID: {', '.join(book_ids)}"
    )

    print(
        "📄 Количество страниц: "
        "определяется автоматически"
    )

    print(
        f"📁 Папка: {output_dir}"
    )

    print("=" * 70)

    # ========================================================
    # ПОДТВЕРЖДЕНИЕ
    # ========================================================

    confirm = ask(
        "\nНачать скачивание? [Y/n]: "
    )

    if confirm.lower() in (
        "n",
        "no",
        "н",
        "нет"
    ):

        print(
            "\n⛔ Отменено."
        )

        return

    # ========================================================
    # КНИГИ
    # ========================================================

    successful_books = 0

    failed_books = []

    total_books = len(
        book_ids
    )

    for number, book_id in enumerate(
        book_ids,
        start=1
    ):

        print()
        print()

        print(
            f"🔵 КНИГА "
            f"{number}/{total_books}"
        )

        # ----------------------------------------------------
        # Отдельный файл
        # ----------------------------------------------------

        output_file = os.path.join(
            output_dir,
            f"book_{book_id}.txt"
        )

        # ----------------------------------------------------
        # Скачать
        # ----------------------------------------------------

        result = download_book(
            book_id,
            output_file
        )

        if result:

            successful_books += 1

        else:

            failed_books.append(
                book_id
            )

        # ----------------------------------------------------
        # Пауза
        # ----------------------------------------------------

        if number < total_books:

            print()

            print(
                f"⏳ Пауза "
                f"{BOOK_DELAY} сек..."
            )

            time.sleep(
                BOOK_DELAY
            )

    # ========================================================
    # ИТОГ
    # ========================================================

    print()
    print()

    print("=" * 70)

    print(
        "🏁 ВСЕ КНИГИ ОБРАБОТАНЫ"
    )

    print("=" * 70)

    print(
        f"📚 Всего: {total_books}"
    )

    print(
        f"✅ Успешно: {successful_books}"
    )

    print(
        f"❌ Ошибок: "
        f"{len(failed_books)}"
    )

    if failed_books:

        print(
            "⚠️ Не скачались: "
            + ", ".join(
                failed_books
            )
        )

    print(
        f"📁 Папка: {output_dir}"
    )

    print("=" * 70)


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\n\n⛔ Остановлено пользователем."
        )

    except Exception as e:

        print(
            f"\n\n❌ Критическая ошибка: {e}"
        )
