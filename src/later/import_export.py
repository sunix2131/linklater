from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from later.database import LinkRepository


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
            root = Path(tmp) / "later-export"
            root.mkdir()
            (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            for table, rows in data.items():
                (root / f"{table}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for file in root.rglob("*"):
                    archive.write(file, file.relative_to(root.parent))
        return path

    def import_zip(self, path: Path, conflict: str = "skip") -> tuple[int, int]:
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(tmp)
            root = Path(tmp) / "later-export"
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("format") != "later-export" or manifest.get("version") != 1:
                raise ValueError("Импорт содержит неподдерживаемую версию формата.")
            data = {
                name: json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
                for name in ("links", "reminders", "tags", "link_tags", "activities", "settings")
                if (root / f"{name}.json").exists()
            }
        return self.repo.import_tables(data, conflict)

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
