# Later

Later is a local desktop app for saving links and bringing them back when they matter: tonight, tomorrow, in a few days, on the weekend, next month, or just in the archive.

The app stores all data on the current device. There are no accounts, analytics, cloud sync, ads, or external backend services.

## Features

- Add links manually, from the clipboard, or by dropping text into the window.
- Normalize URLs and remove tracking parameters in the stored canonical URL while preserving the original URL.
- Fetch title, description, and favicon in a background Qt worker.
- Schedule reminders, postpone links, mark links as read, archive, delete, and restore.
- Browse Today, Queue, Archive, Search, and Settings pages.
- Search with SQLite FTS5 when available and `LIKE` fallback otherwise.
- Export and import ZIP archives, plus CSV export.
- Use light, dark, and system theme settings.
- Use local SQLite with WAL mode and standard OS app directories.

## How Reminders Work

Notifications work while Later is running or minimized to the system tray. If the app is fully closed, it does not pretend to keep scheduling in the background. Due links are resolved and shown the next time Later starts.

Later does not use a cloud server for reminders.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python main.py
pytest
ruff check .
mypy src/later
```

## Privacy

Saved links, notes, tags, settings, favicons, exports, and logs stay in the standard local app directories for the operating system. Metadata requests are made directly from this machine to the saved site.

## Packaging

Native releases should be produced on each target OS with `pyside6-deploy`. The included CI validates linting, typing, and tests; release artifacts are intentionally platform-native.
