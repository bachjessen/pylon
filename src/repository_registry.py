from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def normalize_project_name(value: str) -> str:
    """Return a conservative comparison key for repository/project names."""
    return _NORMALIZE_RE.sub("", value.casefold())


@dataclass(frozen=True)
class ProjectCandidate:
    id: str
    identifier: str
    name: str


@dataclass(frozen=True)
class RepositoryMapping:
    repository_id: int
    full_name: str
    project_id: str
    project_identifier: str
    source: str
    enabled: bool


class AmbiguousProjectMatch(ValueError):
    pass


def suggest_project(
    repository_name: str,
    projects: Iterable[ProjectCandidate],
) -> ProjectCandidate | None:
    """Return one exact normalized match, never a guess."""
    key = normalize_project_name(repository_name)
    matches = [
        project
        for project in projects
        if key
        in {
            normalize_project_name(project.name),
            normalize_project_name(project.identifier),
        }
    ]
    unique = {project.id: project for project in matches}
    if len(unique) > 1:
        raise AmbiguousProjectMatch(repository_name)
    return next(iter(unique.values()), None)


class RepositoryRegistry:
    """SQLite-backed durable identity and mapping store for GitHub webhooks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS repositories (
                    repository_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    html_url TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS repository_mappings (
                    repository_id INTEGER PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    project_identifier TEXT NOT NULL,
                    source TEXT NOT NULL CHECK (source IN ('automatic', 'manual')),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (repository_id) REFERENCES repositories(repository_id)
                );

                CREATE TABLE IF NOT EXISTS processed_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    repository_id INTEGER,
                    event_type TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (repository_id) REFERENCES repositories(repository_id)
                );
                """
            )

    def register_repository(
        self,
        repository_id: int,
        full_name: str,
        html_url: str = "",
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO repositories (repository_id, full_name, html_url)
                VALUES (?, ?, ?)
                ON CONFLICT(repository_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    html_url = excluded.html_url,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (repository_id, full_name, html_url),
            )

    def set_mapping(
        self,
        repository_id: int,
        project: ProjectCandidate,
        *,
        source: str,
        enabled: bool = True,
    ) -> None:
        if source not in {"automatic", "manual"}:
            raise ValueError("source must be automatic or manual")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO repository_mappings (
                    repository_id, project_id, project_identifier, source, enabled
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repository_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    project_identifier = excluded.project_identifier,
                    source = excluded.source,
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    repository_id,
                    project.id,
                    project.identifier,
                    source,
                    int(enabled),
                ),
            )

    def get_mapping(self, repository_id: int) -> RepositoryMapping | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT r.repository_id, r.full_name, m.project_id,
                       m.project_identifier, m.source, m.enabled
                FROM repositories AS r
                JOIN repository_mappings AS m USING (repository_id)
                WHERE r.repository_id = ?
                """,
                (repository_id,),
            ).fetchone()
        if row is None:
            return None
        return RepositoryMapping(
            repository_id=row[0],
            full_name=row[1],
            project_id=row[2],
            project_identifier=row[3],
            source=row[4],
            enabled=bool(row[5]),
        )

    def is_delivery_processed(self, delivery_id: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM processed_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        return row is not None

    def mark_delivery_processed(
        self,
        delivery_id: str,
        event_type: str,
        repository_id: int | None = None,
    ) -> bool:
        """Record completion; false means another worker already recorded it."""
        with self._connect() as db:
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO processed_deliveries (
                    delivery_id, repository_id, event_type
                ) VALUES (?, ?, ?)
                """,
                (delivery_id, repository_id, event_type),
            )
            return cursor.rowcount == 1

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA foreign_keys = ON")
        return db
