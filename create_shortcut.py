#!/usr/bin/env python3
"""Create a Linux desktop launcher pointing to this checkout, wherever it lives."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def desktop_directory():
    if shutil.which("xdg-user-dir"):
        result = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    return Path.home() / "Desktop"


def exec_quote(value):
    value = str(value).replace("\\", "\\\\\\\\").replace('"', '\\\\"')
    value = value.replace("`", "\\\\`").replace("$", "\\\\$").replace("%", "%%")
    return '"' + value + '"'


def main():
    parser = argparse.ArgumentParser(description="Создать ярлык LoveRead Studio для Linux")
    parser.add_argument("--directory", type=Path, help="Папка для ярлыка; при указании меню приложений не изменяется")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if os.name != "posix":
        raise SystemExit("Этот генератор ярлыка предназначен для Linux. Для другой ОС используйте run.py.")
    if any("\n" in str(p) or "\r" in str(p) for p in (root,)):
        raise SystemExit("Путь к программе не должен содержать переводов строк.")
    content = (
        "[Desktop Entry]\nVersion=1.0\nType=Application\nName=LoveRead Studio\n"
        "Comment=Книги с LoveRead и локальный текст → PDF\n"
        f"Exec=/bin/bash {exec_quote(root / 'start.sh')}\n"
        f"Path={root}\nIcon={root / 'gui' / 'icon.svg'}\n"
        "Terminal=false\nCategories=Education;Literature;\nStartupNotify=true\n"
    )
    destinations = [args.directory or desktop_directory()]
    if args.directory is None:
        destinations.append(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "applications")
    for directory in destinations:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "LoveRead Studio.desktop"
        target.write_text(content, encoding="utf-8")
        target.chmod(0o755)
        print("Создан ярлык:", target)


if __name__ == "__main__":
    main()
