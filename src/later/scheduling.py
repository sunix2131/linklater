from __future__ import annotations

import calendar
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from later.domain import ReminderPreset


class SchedulingService:
    def __init__(self, timezone_name: str | None = None) -> None:
        self.timezone = ZoneInfo(timezone_name) if timezone_name else datetime.now().astimezone().tzinfo

    def preset_time(
        self,
        preset: ReminderPreset,
        *,
        now: datetime | None = None,
        default_delivery_time: str = "19:00",
    ) -> datetime | None:
        if preset is ReminderPreset.NONE:
            return None
        now_local = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        delivery = self._parse_time(default_delivery_time)
        date = now_local.date()
        if preset is ReminderPreset.TONIGHT:
            result = datetime.combine(date, delivery, self.timezone)
            if result <= now_local:
                result += timedelta(days=1)
        elif preset is ReminderPreset.TOMORROW:
            result = datetime.combine(date + timedelta(days=1), delivery, self.timezone)
        elif preset is ReminderPreset.THREE_DAYS:
            result = datetime.combine(date + timedelta(days=3), delivery, self.timezone)
        elif preset is ReminderPreset.WEEK:
            result = datetime.combine(date + timedelta(days=7), delivery, self.timezone)
        elif preset is ReminderPreset.WEEKEND:
            target = date if date.weekday() in {5, 6} else date + timedelta(days=(5 - date.weekday()) % 7)
            result = datetime.combine(target, delivery, self.timezone)
            if result <= now_local:
                result += timedelta(days=1)
        elif preset is ReminderPreset.MONTH:
            month = date.month + 1
            year = date.year
            if month == 13:
                month = 1
                year += 1
            day = min(date.day, calendar.monthrange(year, month)[1])
            result = datetime.combine(date.replace(year=year, month=month, day=day), delivery, self.timezone)
        else:
            raise ValueError(f"Unsupported preset: {preset}")
        return result.astimezone(UTC)

    def _parse_time(self, value: str) -> time:
        hour, minute = [int(part) for part in value.split(":", 1)]
        return time(hour=hour, minute=minute)
