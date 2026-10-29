#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Нужен Python 3.10 или новее. См. README.md → Установка.\n' >&2
    exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Нужен Python 3.10 или новее"'
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    printf 'Создаём отдельное окружение .venv…\n'
    python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
"$APP_DIR/.venv/bin/python" -c 'import PySide6, requests, bs4, reportlab; print("Зависимости установлены.")'
printf '\nУстановка завершена. Запуск: bash start.sh\nЯрлык: .venv/bin/python create_shortcut.py\n'
