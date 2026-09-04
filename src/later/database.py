from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from later.domain import Link, LinkStatus, ReminderPreset, ReminderStatus, dt_to_text, parse_dt, utc_now
from later.settings import Settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS links (
    id TEXT PRIMARY KEY,
    original_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    title TEXT,
    description TEXT,
    domain TEXT NOT NULL,
    favicon_path TEXT,
    preview_image_path TEXT,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    opened_at TEXT,
    completed_at TEXT,
    archived_at TEXT,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    link_id TEXT NOT NULL,
    scheduled_at_utc TEXT NOT NULL,
    scheduled_timezone TEXT NOT NULL,
    source_preset TEXT,
    status TEXT NOT NULL,
    shown_at TEXT,
    completed_at TEXT,
    postponed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (link_id) REFERENCES links(id)
);
CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    color TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS link_tags (
    link_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (link_id, tag_id),
    FOREIGN KEY (link_id) REFERENCES links(id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);
CREATE TABLE IF NOT EXISTS activities (
    id TEXT PRIMARY KEY,
    link_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (link_id) REFERENCES links(id)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_status ON links(status);
CREATE INDEX IF NOT EXISTS idx_links_normalized_url ON links(normalized_url);
CREATE INDEX IF NOT EXISTS idx_reminders_link_id ON reminders(link_id);
CREATE INDEX IF NOT EXISTS idx_reminders_scheduled ON reminders(scheduled_at_utc, status);
CREATE INDEX IF NOT EXISTS idx_activities_link_id_created ON activities(link_id, created_at DESC);
"""

LINK_IMPORT_COLUMNS = (
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
)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts_enabled = False
        self.connect().close()
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self.fts_enabled = self._ensure_fts(conn)
            conn.execute("INSERT OR IGNORE INTO migrations(version) VALUES (1)")
            for key, value in Settings().to_dict().items():
                conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))

    def _ensure_fts(self, conn: sqlite3.Connection) -> bool:
        try:
            conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS links_fts USING fts5(
                    title, description, note, domain, original_url, normalized_url,
                    content='links', content_rowid='rowid'
                );
                CREATE TRIGGER IF NOT EXISTS links_ai AFTER INSERT ON links BEGIN
                    INSERT INTO links_fts(rowid,title,description,note,domain,original_url,normalized_url)
                    VALUES (
                        new.rowid,new.title,new.description,new.note,
                        new.domain,new.original_url,new.normalized_url
                    );
                END;
                CREATE TRIGGER IF NOT EXISTS links_ad AFTER DELETE ON links BEGIN
                    INSERT INTO links_fts(links_fts,rowid,title,description,note,domain,original_url,normalized_url)
                    VALUES('delete',old.rowid,old.title,old.description,old.note,old.domain,old.original_url,old.normalized_url);
                END;
                CREATE TRIGGER IF NOT EXISTS links_au AFTER UPDATE ON links BEGIN
                    INSERT INTO links_fts(links_fts,rowid,title,description,note,domain,original_url,normalized_url)
                    VALUES('delete',old.rowid,old.title,old.description,old.note,old.domain,old.original_url,old.normalized_url);
                    INSERT INTO links_fts(rowid,title,description,note,domain,original_url,normalized_url)
                    VALUES (
                        new.rowid,new.title,new.description,new.note,
                        new.domain,new.original_url,new.normalized_url
                    );
                END;
                """
            )
        except sqlite3.OperationalError:
            return False
        return True


class LinkRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def settings(self) -> Settings:
        with self.db.connect() as conn:
            return Settings.from_rows({row["key"]: row["value"] for row in conn.execute("SELECT * FROM settings")})

    def save_settings(self, settings: Settings) -> None:
        with self.db.connect() as conn:
            for key, value in settings.to_dict().items():
                conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, value))

    def add_link(
        self,
        *,
        original_url: str,
        normalized_url: str,
        domain: str,
        title: str | None,
        description: str = "",
        note: str = "",
        tags: Iterable[str] = (),
        scheduled_at_utc: datetime | None,
        timezone_name: str,
        preset: ReminderPreset,
        force_duplicate: bool = False,
    ) -> Link:
        if not force_duplicate:
            duplicate = self.find_active_duplicate(normalized_url)
            if duplicate:
                raise ValueError(f"duplicate:{duplicate.id}")
        now = utc_now()
        link_id = self._id()
        status = LinkStatus.ARCHIVED if scheduled_at_utc is None else LinkStatus.SCHEDULED
        with self.db.connect() as conn:
            conn.execute(
                """
                INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, NULL, NULL, NULL)
                """,
                (
                    link_id,
                    original_url,
                    normalized_url,
                    title or domain,
                    description,
                    domain,
                    note,
                    status.value,
                    dt_to_text(now),
                    dt_to_text(now),
                ),
            )
            if scheduled_at_utc is not None:
                conn.execute(
                    "INSERT INTO reminders VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)",
                    (
                        self._id(),
                        link_id,
                        dt_to_text(scheduled_at_utc),
                        timezone_name,
                        preset.value,
                        ReminderStatus.ACTIVE.value,
                        dt_to_text(now),
                    ),
                )
            self._set_tags(conn, link_id, tags)
            self._activity(conn, link_id, "created", {"scheduled_at": dt_to_text(scheduled_at_utc)})
        return self.get(link_id)

    def get(self, link_id: str) -> Link:
        with self.db.connect() as conn:
            row = conn.execute(self._select_sql("WHERE l.id = ?"), (link_id,)).fetchone()
            if row is None:
                raise KeyError(link_id)
            return self._row_to_link(conn, row)

    def find_active_duplicate(self, normalized_url: str) -> Link | None:
        with self.db.connect() as conn:
            row = conn.execute(
                self._select_sql("WHERE l.normalized_url = ? AND l.status IN ('scheduled', 'due', 'archived')"),
                (normalized_url,),
            ).fetchone()
            return self._row_to_link(conn, row) if row else None

    def today(self, limit: int | None = None) -> list[Link]:
        self.resolve_due()
        sql = self._select_sql(
            """
            WHERE l.status = 'due'
            ORDER BY COALESCE(r.scheduled_at_utc, l.created_at), l.opened_at IS NOT NULL, l.created_at
            """
        )
        if limit:
            sql += " LIMIT ?"
        with self.db.connect() as conn:
            rows = conn.execute(sql, (limit,) if limit else ()).fetchall()
            return [self._row_to_link(conn, row) for row in rows]

    def queue(self) -> list[Link]:
        with self.db.connect() as conn:
            rows = conn.execute(self._select_sql("WHERE l.status = 'scheduled' ORDER BY r.scheduled_at_utc")).fetchall()
            return [self._row_to_link(conn, row) for row in rows]

    def archive(self, include_deleted: bool = True) -> list[Link]:
        statuses = ("completed", "archived", "deleted") if include_deleted else ("completed", "archived")
        placeholders = ",".join("?" for _ in statuses)
        with self.db.connect() as conn:
            rows = conn.execute(
                self._select_sql(f"WHERE l.status IN ({placeholders}) ORDER BY l.updated_at DESC"),
                statuses,
            ).fetchall()
            return [self._row_to_link(conn, row) for row in rows]

    def search(self, query: str, status: str = "all") -> list[Link]:
        query = query.strip()
        if len(query) < 2:
            return []
        status_clause = "" if status == "all" else " AND l.status = ?"
        params: list[str] = []
        with self.db.connect() as conn:
            if self.db.fts_enabled:
                sql = self._select_sql(
                    f"""
                    JOIN links_fts f ON f.rowid = l.rowid
                    WHERE links_fts MATCH ?{status_clause}
                    ORDER BY rank
                    """
                )
                params.append(query.replace('"', ""))
            else:
                like = f"%{query}%"
                sql = self._select_sql(
                    f"""
                    WHERE (l.title LIKE ? OR l.description LIKE ? OR l.note LIKE ?
                    OR l.domain LIKE ? OR l.original_url LIKE ? OR l.normalized_url LIKE ?){status_clause}
                    ORDER BY l.updated_at DESC
                    """
                )
                params.extend([like] * 6)
            if status != "all":
                params.append(status)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_link(conn, row) for row in rows]

    def update_metadata(self, link_id: str, title: str, description: str, favicon_path: str | None = None) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE links SET title=?, description=?, favicon_path=?, updated_at=? WHERE id=?",
                (title, description, favicon_path, dt_to_text(utc_now()), link_id),
            )
            self._activity(conn, link_id, "metadata_loaded", {})

    def action(
        self, link_id: str, action: str, scheduled_at: datetime | None = None, preset: str | None = None
    ) -> None:
        now = utc_now()
        with self.db.connect() as conn:
            if action == "open":
                conn.execute(
                    "UPDATE links SET opened_at=?, updated_at=? WHERE id=?", (dt_to_text(now), dt_to_text(now), link_id)
                )
                self._activity(conn, link_id, "opened", {})
            elif action == "complete":
                conn.execute(
                    "UPDATE links SET status='completed', completed_at=?, updated_at=? WHERE id=?",
                    (dt_to_text(now), dt_to_text(now), link_id),
                )
                conn.execute(
                    "UPDATE reminders SET status='completed', completed_at=? WHERE link_id=? AND status='active'",
                    (dt_to_text(now), link_id),
                )
                self._activity(conn, link_id, "completed", {})
            elif action == "archive":
                conn.execute(
                    "UPDATE links SET status='archived', archived_at=?, updated_at=? WHERE id=?",
                    (dt_to_text(now), dt_to_text(now), link_id),
                )
                self._activity(conn, link_id, "archived", {})
            elif action == "delete":
                conn.execute(
                    "UPDATE links SET status='deleted', deleted_at=?, updated_at=? WHERE id=?",
                    (dt_to_text(now), dt_to_text(now), link_id),
                )
                self._activity(conn, link_id, "deleted", {})
            elif action == "restore":
                conn.execute(
                    "UPDATE links SET status='archived', deleted_at=NULL, updated_at=? WHERE id=?",
                    (dt_to_text(now), link_id),
                )
                self._activity(conn, link_id, "restored", {})
            elif action == "postpone":
                if scheduled_at is None:
                    raise ValueError("scheduled_at is required")
                old = conn.execute(
                    "SELECT scheduled_at_utc FROM reminders WHERE link_id=? AND status='active'", (link_id,)
                ).fetchone()
                conn.execute(
                    "UPDATE reminders SET status='postponed', postponed_at=? WHERE link_id=? AND status='active'",
                    (dt_to_text(now), link_id),
                )
                timezone_name = str(datetime.now().astimezone().tzinfo or "local")
                conn.execute(
                    "INSERT INTO reminders VALUES (?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, ?)",
                    (self._id(), link_id, dt_to_text(scheduled_at), timezone_name, preset, dt_to_text(now)),
                )
                conn.execute("UPDATE links SET status='scheduled', updated_at=? WHERE id=?", (dt_to_text(now), link_id))
                self._activity(
                    conn,
                    link_id,
                    "postponed",
                    {
                        "old": old["scheduled_at_utc"] if old else None,
                        "new": dt_to_text(scheduled_at),
                        "preset": preset,
                    },
                )

    def resolve_due(self) -> int:
        now_text = dt_to_text(utc_now())
        changed = 0
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.link_id FROM reminders r
                JOIN links l ON l.id = r.link_id
                WHERE r.status='active' AND r.scheduled_at_utc <= ?
                AND l.status NOT IN ('completed', 'archived', 'deleted')
                """,
                (now_text,),
            ).fetchall()
            for row in rows:
                conn.execute("UPDATE links SET status='due', updated_at=? WHERE id=?", (now_text, row["link_id"]))
                conn.execute("UPDATE reminders SET status='shown', shown_at=? WHERE id=?", (now_text, row["id"]))
                self._activity(conn, row["link_id"], "shown_today", {})
                changed += 1
        return changed

    def purge_deleted(self, older_than_days: int = 30) -> int:
        cutoff = dt_to_text(utc_now() - timedelta(days=older_than_days))
        with self.db.connect() as conn:
            rows = conn.execute("SELECT id FROM links WHERE status='deleted' AND deleted_at < ?", (cutoff,)).fetchall()
            for row in rows:
                conn.execute("DELETE FROM link_tags WHERE link_id=?", (row["id"],))
                conn.execute("DELETE FROM reminders WHERE link_id=?", (row["id"],))
                conn.execute("DELETE FROM activities WHERE link_id=?", (row["id"],))
                conn.execute("DELETE FROM links WHERE id=?", (row["id"],))
            return len(rows)

    def all_tables(self) -> dict[str, list[dict[str, object]]]:
        with self.db.connect() as conn:
            return {
                table: [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
                for table in ("links", "reminders", "tags", "link_tags", "activities", "settings")
            }

    def import_tables(self, data: dict[str, list[dict[str, object]]], conflict: str = "skip") -> tuple[int, int]:
        if conflict not in {"skip", "update", "separate"}:
            raise ValueError("unknown import conflict mode")
        links_added = tags_added = 0
        tag_ids: dict[str, str] = {}
        link_ids: dict[str, str] = {}
        skipped_link_ids: set[str] = set()
        with self.db.connect() as conn:
            for row in data.get("tags", []):
                source_id = str(row["id"])
                existing = conn.execute("SELECT id FROM tags WHERE name=?", (row["name"],)).fetchone()
                if existing:
                    tag_ids[source_id] = existing["id"]
                    if conflict == "update":
                        conn.execute("UPDATE tags SET color=? WHERE id=?", (row["color"], existing["id"]))
                else:
                    target_id = source_id
                    if conn.execute("SELECT 1 FROM tags WHERE id=?", (target_id,)).fetchone():
                        target_id = self._id()
                    conn.execute(
                        "INSERT INTO tags VALUES (?, ?, ?, ?)",
                        (target_id, row["name"], row["color"], row["created_at"]),
                    )
                    tag_ids[source_id] = target_id
                    tags_added += 1
            for row in data.get("links", []):
                source_id = str(row["id"])
                existing = conn.execute(
                    "SELECT id FROM links WHERE normalized_url=? AND status IN ('scheduled','due','archived')",
                    (row["normalized_url"],),
                ).fetchone()
                if existing and conflict == "skip":
                    skipped_link_ids.add(source_id)
                    continue
                if existing and conflict == "update":
                    target_id = existing["id"]
                    conn.execute(
                        f"UPDATE links SET {','.join(f'{column}=?' for column in LINK_IMPORT_COLUMNS)} WHERE id=?",
                        [row[column] for column in LINK_IMPORT_COLUMNS] + [target_id],
                    )
                else:
                    target_id = source_id
                    id_exists = conn.execute("SELECT 1 FROM links WHERE id=?", (target_id,)).fetchone()
                    if id_exists and conflict == "skip":
                        skipped_link_ids.add(source_id)
                        continue
                    if id_exists and conflict == "update":
                        conn.execute(
                            f"UPDATE links SET {','.join(f'{column}=?' for column in LINK_IMPORT_COLUMNS)} WHERE id=?",
                            [row[column] for column in LINK_IMPORT_COLUMNS] + [target_id],
                        )
                        link_ids[source_id] = target_id
                        links_added += 1
                        continue
                    if existing or id_exists:
                        target_id = self._id()
                    link_values = [target_id, *(row[column] for column in LINK_IMPORT_COLUMNS)]
                    conn.execute(
                        "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", link_values
                    )
                link_ids[source_id] = target_id
                links_added += 1
            for table, cols in {
                "reminders": (
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
                ),
                "link_tags": ("link_id", "tag_id"),
                "activities": ("id", "link_id", "activity_type", "payload_json", "created_at"),
            }.items():
                for row in data.get(table, []):
                    source_link_id = str(row["link_id"])
                    if source_link_id in skipped_link_ids:
                        continue
                    relation_values = {column: row[column] for column in cols}
                    relation_values["link_id"] = link_ids.get(source_link_id, source_link_id)
                    if table == "link_tags":
                        source_tag_id = str(row["tag_id"])
                        relation_values["tag_id"] = tag_ids.get(source_tag_id, source_tag_id)
                    conn.execute(
                        f"INSERT OR IGNORE INTO {table} VALUES ({','.join('?' for _ in cols)})",
                        [relation_values[column] for column in cols],
                    )
            for row in data.get("settings", []):
                if conflict == "update":
                    conn.execute(
                        "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                        (row["key"], row["value"]),
                    )
                else:
                    conn.execute(
                        "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                        (row["key"], row["value"]),
                    )
        return links_added, tags_added

    def _set_tags(self, conn: sqlite3.Connection, link_id: str, tags: Iterable[str]) -> None:
        palette = ["#3b82f6", "#16a34a", "#f59e0b", "#ef4444", "#8b5cf6", "#0891b2"]
        for idx, name in enumerate(dict.fromkeys(tag.strip() for tag in tags if tag.strip())):
            if len(name) > 32:
                raise ValueError("Название тега не должно быть длиннее 32 символов.")
            tag_id = self._id()
            conn.execute(
                "INSERT OR IGNORE INTO tags VALUES (?, ?, ?, ?)",
                (tag_id, name, palette[idx % len(palette)], dt_to_text(utc_now())),
            )
            row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            conn.execute("INSERT OR IGNORE INTO link_tags VALUES (?, ?)", (link_id, row["id"]))
            self._activity(conn, link_id, "tag_added", {"name": name})

    def _activity(self, conn: sqlite3.Connection, link_id: str, activity: str, payload: dict[str, object]) -> None:
        conn.execute(
            "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
            (self._id(), link_id, activity, json.dumps(payload, ensure_ascii=False), dt_to_text(utc_now())),
        )

    def _row_to_link(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Link:
        tags = tuple(
            tag["name"]
            for tag in conn.execute(
                "SELECT t.name FROM tags t JOIN link_tags lt ON lt.tag_id=t.id WHERE lt.link_id=? ORDER BY t.name",
                (row["id"],),
            )
        )
        count = conn.execute(
            "SELECT COUNT(*) c FROM activities WHERE link_id=? AND activity_type='postponed'", (row["id"],)
        ).fetchone()["c"]
        return Link(
            id=row["id"],
            original_url=row["original_url"],
            normalized_url=row["normalized_url"],
            title=row["title"],
            description=row["description"],
            domain=row["domain"],
            favicon_path=row["favicon_path"],
            preview_image_path=row["preview_image_path"],
            note=row["note"],
            status=LinkStatus(row["status"]),
            created_at=parse_dt(row["created_at"]) or utc_now(),
            updated_at=parse_dt(row["updated_at"]) or utc_now(),
            opened_at=parse_dt(row["opened_at"]),
            completed_at=parse_dt(row["completed_at"]),
            archived_at=parse_dt(row["archived_at"]),
            deleted_at=parse_dt(row["deleted_at"]),
            scheduled_at_utc=parse_dt(row["scheduled_at_utc"]),
            tags=tags,
            postpone_count=count,
        )

    def _select_sql(self, where: str) -> str:
        return f"""
        SELECT l.*, r.scheduled_at_utc FROM links l
        LEFT JOIN reminders r ON r.link_id=l.id AND r.status IN ('active','shown')
        {where}
        """

    def _id(self) -> str:
        return str(uuid.uuid4())
