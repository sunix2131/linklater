from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from later.database import LinkRepository

EXPORT_ROOT = "later-export"
TABLE_COLUMNS = {
    "links": {
        "id",
        "original_url",
        "normalized_url",
        "title",
        "description",
        "domain",
        "favicon_path",
        "preview_image_path",
        "note",
        "status",
        "created_at",
        "updated_at",
        "opened_at",
        "completed_at",
        "archived_at",
        "deleted_at",
    },
    "reminders": {
        "id",
        "link_id",
        "scheduled_at_utc",
        "scheduled_timezone",
        "source_preset",
        "status",
        "shown_at",
        "completed_at",
        "postponed_at",
        "created_at",
    },
    "tags": {"id", "name", "color", "created_at"},
    "link_tags": {"link_id", "tag_id"},
    "activities": {"id", "link_id", "activity_type", "payload_json", "created_at"},
    "settings": {"key", "value"},
}
MAX_MEMBER_SIZE = 10 * 1024 * 1024
MAX_ARCHIVE_SIZE = 25 * 1024 * 1024


class ImportExportService:
    def __init__(self, repo: LinkRepository) -> None:
        self.repo = repo

    def export_zip(self, path: Path) -> Path:
        data = self.repo.all_tables()
        manifest = {
            "format": "later-export",
            "version": 1,
            "exported_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / EXPORT_ROOT
            root.mkdir()
            (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            for table, rows in data.items():
                (root / f"{table}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file in root.rglob("*"):
                    archive.write(file, file.relative_to(root.parent))
        return path

    def import_zip(self, path: Path, conflict: str = "skip") -> tuple[int, int]:
        if conflict not in {"skip", "update", "separate"}:
            raise ValueError("Неизвестный режим разрешения конфликтов.")

        try:
            with zipfile.ZipFile(path) as archive:
                members = {item.filename: item for item in archive.infolist() if not item.is_dir()}
                if len(members) != sum(not item.is_dir() for item in archive.infolist()):
                    raise ValueError("Архив содержит повторяющиеся имена файлов.")

                allowed = {f"{EXPORT_ROOT}/manifest.json"} | {
                    f"{EXPORT_ROOT}/{name}.json" for name in TABLE_COLUMNS
                }
                unexpected = set(members) - allowed
                if unexpected:
                    raise ValueError("Архив содержит файлы, не относящиеся к экспорту Later.")

                total_size = sum(item.file_size for item in members.values())
                if total_size > MAX_ARCHIVE_SIZE or any(item.file_size > MAX_MEMBER_SIZE for item in members.values()):
                    raise ValueError("Архив импорта слишком большой.")
                if any(item.flag_bits & 0x1 for item in members.values()):
                    raise ValueError("Зашифрованные архивы не поддерживаются.")

                manifest = self._read_json(archive, members, f"{EXPORT_ROOT}/manifest.json")
                valid_manifest = (
                    isinstance(manifest, dict)
                    and manifest.get("format") == "later-export"
                    and manifest.get("version") == 1
                )
                if not valid_manifest:
                    raise ValueError("Импорт содержит неподдерживаемую версию формата.")

                data: dict[str, list[dict[str, object]]] = {}
                for name, columns in TABLE_COLUMNS.items():
                    member_name = f"{EXPORT_ROOT}/{name}.json"
                    if member_name not in members:
                        continue
                    rows = self._read_json(archive, members, member_name)
                    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                        raise ValueError(f"Файл {name}.json имеет неверную структуру.")
                    for row in rows:
                        unknown = set(row) - columns
                        if unknown:
                            raise ValueError(f"Файл {name}.json содержит неизвестные поля.")
                        missing = columns - set(row)
                        if missing:
                            raise ValueError(f"Файл {name}.json не содержит обязательные поля.")
                    data[name] = rows
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise ValueError("Не удалось прочитать экспорт Later.") from exc
        return self.repo.import_tables(data, conflict)

    def _read_json(
        self, archive: zipfile.ZipFile, members: dict[str, zipfile.ZipInfo], name: str
    ) -> object:
        member = members.get(name)
        if member is None:
            raise KeyError(name)
        return json.loads(archive.read(member).decode("utf-8"))

    def export_csv(self, path: Path) -> Path:
        links = self.repo.today(None) + self.repo.queue() + self.repo.archive()
        seen: set[str] = set()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["Title", "URL", "Domain", "Note", "Status", "Scheduled date", "Tags", "Created date", "Completed date"]
            )
            for link in links:
                if link.id in seen:
                    continue
                seen.add(link.id)
                writer.writerow(
                    [
                        link.title or link.domain,
                        link.original_url,
                        link.domain,
                        link.note,
                        link.status.value,
                        link.scheduled_at_utc.isoformat() if link.scheduled_at_utc else "",
                        ", ".join(link.tags),
                        link.created_at.isoformat(),
                        link.completed_at.isoformat() if link.completed_at else "",
                    ]
                )
        return path
