from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Settings:
    language: str = "ru"
    theme: str = "system"
    daily_limit: int = 5
    default_delivery_time: str = "19:00"
    close_behavior: str = "ask"
    notifications_enabled: bool = True
    tray_enabled: bool = True
    fetch_favicons: bool = True
    fetch_preview_images: bool = False
    allow_local_network_urls: bool = False
    metadata_timeout_seconds: int = 10
    recent_tags_limit: int = 12

    def to_dict(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}

    @classmethod
    def from_rows(cls, rows: dict[str, str]) -> Settings:
        defaults = cls()
        values = asdict(defaults)
        for key, raw in rows.items():
            if key not in values:
                continue
            current = values[key]
            if isinstance(current, bool):
                values[key] = raw.lower() in {"1", "true", "yes", "on"}
            elif isinstance(current, int):
                values[key] = int(raw)
            else:
                values[key] = raw
        return cls(**values)
