from __future__ import annotations

import json
import zipfile

import pytest

from later.database import Database, LinkRepository
from later.domain import ReminderPreset
from later.import_export import ImportExportService


def test_export_and_import_zip(tmp_path) -> None:
    source = LinkRepository(Database(tmp_path / "source.db"))
    source.add_link(
        original_url="https://example.com",
        normalized_url="https://example.com/",
        domain="example.com",
        title="Example",
        tags=["Work"],
        scheduled_at_utc=None,
        timezone_name="UTC",
        preset=ReminderPreset.NONE,
    )
    archive = tmp_path / "export.zip"
    ImportExportService(source).export_zip(archive)

    target = LinkRepository(Database(tmp_path / "target.db"))
    links, tags = ImportExportService(target).import_zip(archive)

    assert links == 1
    assert tags == 1
    assert target.search("Example")


def write_archive(path, files: dict[str, object]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, json.dumps(value))


def manifest() -> dict[str, object]:
    return {"format": "later-export", "version": 1, "exported_at": "2026-09-04T00:00:00Z"}


def test_import_rejects_files_outside_export_directory(tmp_path) -> None:
    archive = tmp_path / "unsafe.zip"
    write_archive(
        archive,
        {
            "later-export/manifest.json": manifest(),
            "../outside.json": {"unexpected": True},
        },
    )
    target = LinkRepository(Database(tmp_path / "target.db"))

    with pytest.raises(ValueError, match="не относящиеся"):
        ImportExportService(target).import_zip(archive)

    assert not (tmp_path / "outside.json").exists()


def test_import_rejects_unknown_table_fields(tmp_path) -> None:
    archive = tmp_path / "unknown-field.zip"
    write_archive(
        archive,
        {
            "later-export/manifest.json": manifest(),
            "later-export/links.json": [{"id": "1", "normalized_url": "https://example.com", "bad_column": 1}],
        },
    )
    target = LinkRepository(Database(tmp_path / "target.db"))

    with pytest.raises(ValueError, match="неизвестные поля"):
        ImportExportService(target).import_zip(archive)


def test_import_rejects_incomplete_table_rows(tmp_path) -> None:
    archive = tmp_path / "missing-fields.zip"
    write_archive(
        archive,
        {
            "later-export/manifest.json": manifest(),
            "later-export/links.json": [{"id": "1", "normalized_url": "https://example.com"}],
        },
    )
    target = LinkRepository(Database(tmp_path / "target.db"))

    with pytest.raises(ValueError, match="обязательные поля"):
        ImportExportService(target).import_zip(archive)


def test_import_rejects_invalid_conflict_mode(tmp_path) -> None:
    source = LinkRepository(Database(tmp_path / "source.db"))
    archive = tmp_path / "export.zip"
    ImportExportService(source).export_zip(archive)
    target = LinkRepository(Database(tmp_path / "target.db"))

    with pytest.raises(ValueError, match="режим"):
        ImportExportService(target).import_zip(archive, "overwrite")


def test_import_skips_duplicate_link_and_its_related_rows(tmp_path) -> None:
    source = LinkRepository(Database(tmp_path / "source.db"))
    source.add_link(
        original_url="https://example.com",
        normalized_url="https://example.com/",
        domain="example.com",
        title="From export",
        tags=["Imported"],
        scheduled_at_utc=None,
        timezone_name="UTC",
        preset=ReminderPreset.NONE,
    )
    archive = tmp_path / "export.zip"
    ImportExportService(source).export_zip(archive)

    target = LinkRepository(Database(tmp_path / "target.db"))
    existing = target.add_link(
        original_url="https://example.com",
        normalized_url="https://example.com/",
        domain="example.com",
        title="Keep this title",
        scheduled_at_utc=None,
        timezone_name="UTC",
        preset=ReminderPreset.NONE,
    )

    links, tags = ImportExportService(target).import_zip(archive, "skip")

    assert links == 0
    assert tags == 1
    assert target.get(existing.id).title == "Keep this title"
