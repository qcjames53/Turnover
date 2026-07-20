import os
import sqlite3
from pathlib import Path

from . import migrations
from .map import Message
from .pbap import Contact

_MESSAGE_COLUMNS = (
    "folder",
    "handle",
    "datetime",
    "sender_addressing",
    "recipient_addressing",
    "text",
)
_MESSAGE_HANDLES_NEEDED = 25 # iPhones limit to 10 most recent messages so 25 is more than safe


def _db_path() -> Path:
    """
    Resolves the path to the local sqlite cache, creating its parent directory if needed.

    :returns: Path to turnover.db under XDG_STATE_HOME.
    """
    state_home = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    path = Path(state_home) / "turnover" / "turnover.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    """
    Opens a new connection to the local sqlite cache.

    :returns: Open sqlite3 connection to turnover.db.
    """
    return sqlite3.connect(_db_path())


def migrate() -> None:
    """
    Applies any pending schema migrations. Safe to call repeatedly.
    """
    conn = _connect()
    try:
        migrations.migrate(conn)
    finally:
        conn.close()


def known_contact_handles() -> set[str]:
    """
    Lists contact handles already cached -- cheap enough (no vcard-fetched number) to call before
    every incremental sync without pulling in the full contact rows via list_contacts().

    :returns: Set of cached contact handles.
    """
    conn = _connect()
    try:
        rows = conn.execute("SELECT handle FROM contacts").fetchall()
    finally:
        conn.close()
    return {handle for (handle,) in rows}


def save_contacts(contacts: list[Contact]) -> None:
    """
    Upserts `contacts` into the cache, keyed on handle. Contact.number is str | None, but the
    number column is NOT NULL -- coerce None to "" here rather than relax the schema.

    :param contacts: Contacts to upsert; a no-op if empty.
    """
    if not contacts:
        return
    conn = _connect()
    try:
        conn.executemany(
            """
            INSERT INTO contacts (handle, name, number) VALUES (?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET name=excluded.name, number=excluded.number
            """,
            [(c.handle, c.name, c.number or "") for c in contacts],
        )
        conn.commit()
    finally:
        conn.close()


def list_contacts() -> list[Contact]:
    """
    Lists all cached contacts, sorted by name.

    :returns: List of Contact objects.
    """
    conn = _connect()
    try:
        rows = conn.execute("SELECT handle, name, number FROM contacts ORDER BY name COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    return [Contact(handle=handle, name=name, number=number) for handle, name, number in rows]


def known_message_handles() -> set[tuple[str, str]]:
    """
    Lists (folder, handle) pairs among the _MESSAGE_HANDLES_NEEDED most recently cached messages
    -- MAP's msg-listing only ever surfaces a phone's most recent messages anyway, so checking
    further back just costs processing on every incremental sync for handles that could never
    come back around.

    :returns: Set of cached (folder, handle) pairs.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT folder, handle FROM messages ORDER BY datetime DESC LIMIT ?",
            (_MESSAGE_HANDLES_NEEDED,),
        ).fetchall()
    finally:
        conn.close()
    return {(folder, handle) for folder, handle in rows}


def save_messages(messages: list[Message]) -> None:
    """Upserts `messages` into the cache, keyed on (folder, handle).

    A brand-new (folder, handle) is inserted with local_read=0 (unread).
    An already-cached one (only possible via `messages sync --full`, since
    incremental sync never returns already-known handles at all) has its
    protocol data refreshed but local_read deliberately left alone --
    otherwise a --full resync would silently mark your already-read inbox
    unread again, which isn't what "full" is for.

    :param messages: Messages to upsert.
    """
    conn = _connect()
    try:
        columns = ", ".join(_MESSAGE_COLUMNS)
        placeholders = ", ".join("?" * len(_MESSAGE_COLUMNS))
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in _MESSAGE_COLUMNS if c not in ("folder", "handle"))
        conn.executemany(
            f"""
            INSERT INTO messages ({columns}, local_read)
            VALUES ({placeholders}, 0)
            ON CONFLICT(folder, handle) DO UPDATE SET {update_clause}
            """,
            [
                (
                    m.folder,
                    m.handle,
                    m.datetime,
                    m.sender_addressing,
                    m.recipient_addressing,
                    m.text,
                )
                for m in messages
            ],
        )
        conn.commit()
    finally:
        conn.close()


def mark_read(handles: list[tuple[str, str]]) -> None:
    """
    Marks the given (folder, handle) messages as locally read -- called after a conversation is
    actually displayed to the user.

    :param handles: (folder, handle) pairs to mark read; a no-op if empty.
    """
    if not handles:
        return
    conn = _connect()
    try:
        conn.executemany("UPDATE messages SET local_read = 1 WHERE folder = ? AND handle = ?", handles)
        conn.commit()
    finally:
        conn.close()


def list_messages() -> list[Message]:
    """
    Lists all cached messages, ordered by datetime.

    :returns: List of Message objects.
    """
    columns = ", ".join(_MESSAGE_COLUMNS)
    conn = _connect()
    try:
        rows = conn.execute(f"SELECT {columns}, local_read FROM messages ORDER BY datetime").fetchall()
    finally:
        conn.close()

    return [
        Message(
            folder=folder,
            handle=handle,
            datetime=dt,
            sender_addressing=sender_addressing,
            recipient_addressing=recipient_addressing,
            text=text,
            local_read=bool(local_read),
        )
        for folder, handle, dt, sender_addressing, recipient_addressing, text, local_read in rows
    ]


def clear() -> None:
    """
    Deletes the local sqlite cache file, if it exists.
    """
    _db_path().unlink(missing_ok=True)
