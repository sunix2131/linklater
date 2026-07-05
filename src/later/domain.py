from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class LinkStatus(StrEnum):
    SCHEDULED = "scheduled"
    DUE = "due"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ReminderStatus(StrEnum):
    ACTIVE = "active"
    SHOWN = "shown"
    COMPLETED = "completed"
    POSTPONED = "postponed"


class ReminderPreset(StrEnum):
    TONIGHT = "tonight"
    TOMORROW = "tomorrow"
    THREE_DAYS = "three_days"
    WEEKEND = "weekend"
    WEEK = "week"
    MONTH = "month"
    CUSTOM = "custom"
    NONE = "none"


@dataclass(frozen=True)
class LinkMetadata:
    title: str
    description: str = ""
    favicon_path: str | None = None
    preview_image_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Link:
    id: str
    original_url: str
    normalized_url: str
    title: str | None
    description: str | None
    domain: str
    favicon_path: str | None
    preview_image_path: str | None
    note: str
    status: LinkStatus
    created_at: datetime
    updated_at: datetime
    opened_at: datetime | None = None
    completed_at: datetime | None = None
    archived_at: datetime | None = None
    deleted_at: datetime | None = None
    tags: tuple[str, ...] = ()
    scheduled_at_utc: datetime | None = None
    postpone_count: int = 0


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def dt_to_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
