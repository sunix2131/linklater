from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from PySide6.QtWidgets import QApplication

from later.database import Database, LinkRepository
from later.paths import AppPaths
from later.presentation.main_window import MainWindow


def run() -> int:
    paths = AppPaths.create()
    handler = TimedRotatingFileHandler(paths.log_dir / "later.log", when="midnight", backupCount=14, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    app = QApplication(sys.argv)
    app.setApplicationName("Later")
    repo = LinkRepository(Database(paths.db_path))
    window = MainWindow(repo, paths)
    window.show()
    return app.exec()
