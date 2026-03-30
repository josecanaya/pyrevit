from __future__ import annotations

import argparse
import sys
from pathlib import Path

from btz_console.app import AppState
from btz_console.ui import MainWindow
from btz_console.ui.theme import build_dark_stylesheet


def _resolve_public_dir(cli_value: str) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    cwd_public = (Path.cwd() / "public").resolve()
    if cwd_public.exists():
        return cwd_public
    repo_public = (Path(__file__).resolve().parents[1] / "public").resolve()
    return repo_public


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="BTZ Console")
    parser.add_argument(
        "--public-dir",
        default="",
        help="Ruta de carpeta public/ del flujo BTZ",
    )
    parser.add_argument(
        "--section",
        default="Prepare",
        choices=["Prepare", "Groups", "Suggestions", "Confirm", "Report"],
        help="Sección inicial",
    )
    parser.add_argument(
        "--open-prompt",
        action="store_true",
        help="Abre Prepare con foco en editor de prompt",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    public_dir = _resolve_public_dir(args.public_dir)

    try:
        from PySide6.QtWidgets import QApplication
    except Exception as ex:
        print("PySide6 no disponible: {}".format(ex))
        print("Instalar con: pip install PySide6")
        return 2

    app = QApplication(sys.argv)
    app.setStyleSheet(build_dark_stylesheet())

    state = AppState(public_dir=public_dir)
    window = MainWindow(state, initial_page=args.section, open_prompt=bool(args.open_prompt))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

