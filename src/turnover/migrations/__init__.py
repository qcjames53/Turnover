"""
Schema migrations for the local sqlite cache (see db.py).

Each migration module exposes `up(conn)` and `down(conn)`. Add a new one by
creating `mYYYYMMDDHHMMSS_description.py` (current UTC datetime) and
registering it in `_MIGRATIONS` below, keyed on that same timestamp.
"""

import sqlite3

from . import (
    m20260720194244_initial,
    m20260722151200_conversation_addressing,
    m20260722160000_contact_numbers,
)

_MIGRATIONS = [
    (20260720194244, m20260720194244_initial),
    (20260722151200, m20260722151200_conversation_addressing),
    (20260722160000, m20260722160000_contact_numbers),
]


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER NOT NULL PRIMARY KEY)")


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_schema_migrations_table(conn)
    (version,) = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return version or 0


def migrate(conn: sqlite3.Connection, target: int | None = None) -> None:
    """
    Migrates `conn` to `target`, applying `up()`s if `target` is ahead of the current version or
    `down()`s (in reverse order) if it's behind. Safe to call repeatedly -- a no-op once `conn` is
    already at `target`.

    :param conn: Open sqlite3 connection to migrate.
    :param target: Migration version to migrate to. Omit for the latest registered migration.
    """
    _ensure_schema_migrations_table(conn)
    target = _MIGRATIONS[-1][0] if target is None else target
    current = current_version(conn)

    if target > current:
        for version, module in _MIGRATIONS:
            if current < version <= target:
                module.up(conn)
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
    elif target < current:
        for version, module in reversed(_MIGRATIONS):
            if target < version <= current:
                module.down(conn)
                conn.execute("DELETE FROM schema_migrations WHERE version = ?", (version,))

    conn.commit()
