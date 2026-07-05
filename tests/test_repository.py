from __future__ import annotations

from datetime import UTC, datetime, timedelta

from later.database import Database, LinkRepository
from later.domain import LinkStatus, ReminderPreset, utc_now


def repo(tmp_path):
    return LinkRepository(Database(tmp_path / "later.db"))


def test_add_link_and_duplicate_detection(tmp_path) -> None:
    repository = repo(tmp_path)
    repository.add_link(
        original_url="https://example.com/?utm_source=x",
        normalized_url="https://example.com/",
        domain="example.com",
        title="Example",
        note="Read",
        tags=["Учёба"],
        scheduled_at_utc=utc_now() + timedelta(days=1),
        timezone_name="UTC",
        preset=ReminderPreset.TOMORROW,
    )

    duplicate = repository.find_active_duplicate("https://example.com/")

    assert duplicate is not None
    assert duplicate.tags == ("Учёба",)


def test_due_resolution_and_today_limit(tmp_path) -> None:
    repository = repo(tmp_path)
    for index in range(3):
        repository.add_link(
            original_url=f"https://example.com/{index}",
            normalized_url=f"https://example.com/{index}",
            domain="example.com",
            title=f"Link {index}",
            scheduled_at_utc=utc_now() - timedelta(minutes=index + 1),
            timezone_name="UTC",
            preset=ReminderPreset.CUSTOM,
        )

    assert repository.resolve_due() == 3
    today = repository.today(2)

    assert len(today) == 2
    assert all(link.status is LinkStatus.DUE for link in today)


def test_postpone_archive_delete_restore(tmp_path) -> None:
    repository = repo(tmp_path)
    link = repository.add_link(
        original_url="https://example.com/a",
        normalized_url="https://example.com/a",
        domain="example.com",
        title="A",
        scheduled_at_utc=utc_now() - timedelta(minutes=1),
        timezone_name="UTC",
        preset=ReminderPreset.CUSTOM,
    )

    repository.resolve_due()
    repository.action(link.id, "postpone", datetime(2026, 7, 10, 19, 0, tzinfo=UTC), "tomorrow")
    assert repository.get(link.id).status is LinkStatus.SCHEDULED
    repository.action(link.id, "archive")
    assert repository.get(link.id).status is LinkStatus.ARCHIVED
    repository.action(link.id, "delete")
    assert repository.get(link.id).status is LinkStatus.DELETED
    repository.action(link.id, "restore")
    assert repository.get(link.id).status is LinkStatus.ARCHIVED


def test_search_like_fallback(tmp_path) -> None:
    repository = repo(tmp_path)
    repository.db.fts_enabled = False
    repository.add_link(
        original_url="https://example.com/python",
        normalized_url="https://example.com/python",
        domain="example.com",
        title="Python article",
        note="desktop app",
        scheduled_at_utc=None,
        timezone_name="UTC",
        preset=ReminderPreset.NONE,
    )

    results = repository.search("python")

    assert len(results) == 1
