# Architecture

Later uses a small layered Python architecture:

- `domain.py`: statuses, presets, value objects, and time helpers.
- `database.py`: SQLite connection, migrations, repositories, FTS5 setup, and fallback search.
- `url_service.py`, `scheduling.py`, `metadata.py`, `import_export.py`: application services.
- `presentation/`: PySide6 widgets, dialogs, tray integration, scheduler timer, and background workers.

The UI talks to repositories and services. SQL, HTTP, and filesystem concerns stay out of widget code where practical.
