from __future__ import annotations

from datetime import UTC, datetime

import pytest

from later.domain import ReminderPreset
from later.scheduling import SchedulingService
from later.url_service import UrlError, UrlNormalizationService


def test_normalizes_url_and_removes_tracking_params() -> None:
    result = UrlNormalizationService().normalize("Example.COM:443/path?b=2&utm_source=x&a=1&fbclid=no#section")

    assert result.original == "https://Example.COM:443/path?b=2&utm_source=x&a=1&fbclid=no#section"
    assert result.normalized == "https://example.com/path?a=1&b=2"
    assert result.domain == "example.com"


def test_rejects_blocked_scheme() -> None:
    with pytest.raises(UrlError):
        UrlNormalizationService().normalize("javascript:alert(1)")


@pytest.mark.parametrize("url", ["http://foo.localhost/", "http://printer/", "http://[::1]/", "http://224.0.0.1/"])
def test_rejects_non_public_targets(url: str) -> None:
    with pytest.raises(UrlError):
        UrlNormalizationService().normalize(url)


def test_ipv6_and_missing_scheme_keep_a_browser_openable_url() -> None:
    service = UrlNormalizationService()
    assert (
        service.normalize("example.com/a?utm_source=feed#paragraph").original
        == "https://example.com/a?utm_source=feed#paragraph"
    )
    assert service.normalize("http://[::1]:8080/a", allow_local=True).normalized == "http://[::1]:8080/a"
    with pytest.raises(UrlError):
        service.normalize("https://user:password@example.com")


def test_rejects_local_url_by_default() -> None:
    with pytest.raises(UrlError):
        UrlNormalizationService().normalize("http://127.0.0.1:8000")


def test_allows_local_url_when_enabled() -> None:
    result = UrlNormalizationService().normalize("http://127.0.0.1:8000", allow_local=True)

    assert result.normalized == "http://127.0.0.1:8000/"


def test_tonight_moves_to_tomorrow_after_delivery_time() -> None:
    service = SchedulingService("UTC")
    now = datetime(2026, 7, 5, 20, 0, tzinfo=UTC)

    result = service.preset_time(ReminderPreset.TONIGHT, now=now, default_delivery_time="19:00")

    assert result == datetime(2026, 7, 6, 19, 0, tzinfo=UTC)


def test_weekend_uses_nearest_saturday() -> None:
    service = SchedulingService("UTC")
    now = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)

    result = service.preset_time(ReminderPreset.WEEKEND, now=now, default_delivery_time="19:00")

    assert result == datetime(2026, 7, 11, 19, 0, tzinfo=UTC)


def test_month_uses_last_day_when_needed() -> None:
    service = SchedulingService("UTC")
    now = datetime(2027, 1, 31, 12, 0, tzinfo=UTC)

    result = service.preset_time(ReminderPreset.MONTH, now=now, default_delivery_time="19:00")

    assert result == datetime(2027, 2, 28, 19, 0, tzinfo=UTC)
