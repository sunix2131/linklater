from __future__ import annotations

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
