from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir, user_log_dir

APP_NAME = "Later"
APP_AUTHOR = "Later"


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path
    cache_dir: Path
    log_dir: Path
    db_path: Path
    settings_path: Path
    exports_dir: Path
    backups_dir: Path
    favicons_dir: Path
    preview_images_dir: Path

    @classmethod
    def create(cls) -> AppPaths:
        data = Path(user_data_dir(APP_NAME, APP_AUTHOR))
        cache = Path(user_cache_dir(APP_NAME, APP_AUTHOR))
        logs = Path(user_log_dir(APP_NAME, APP_AUTHOR))
        paths = cls(
            data_dir=data,
            cache_dir=cache,
            log_dir=logs,
            db_path=data / "later.db",
            settings_path=data / "settings.toml",
            exports_dir=data / "exports",
            backups_dir=data / "backups",
            favicons_dir=cache / "favicons",
            preview_images_dir=cache / "preview_images",
        )
        for path in (
            paths.data_dir,
            paths.cache_dir,
            paths.log_dir,
            paths.exports_dir,
            paths.backups_dir,
            paths.favicons_dir,
            paths.preview_images_dir,
            cache / "metadata",
            cache / "temporary",
        ):
            path.mkdir(parents=True, exist_ok=True)
        return paths
