#!/usr/bin/env bash
set -Eeuo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    if "$APP_DIR/.venv/bin/python" -c 'import PySide6, requests, bs4, reportlab' >/dev/null 2>&1; then
        exec "$APP_DIR/.venv/bin/python" "$APP_DIR/run.py" "$@"
    fi
elif python3 -c 'import PySide6, requests, bs4, reportlab' >/dev/null 2>&1; then
    exec python3 "$APP_DIR/run.py" "$@"
fi
bash "$APP_DIR/install.sh"
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/run.py" "$@"
