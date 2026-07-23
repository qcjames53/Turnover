import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import migrations
from .pbap import Contact


@dataclass
class Message:
    handle: str
    folder: str
    datetime: str
    text: str
    sender_addressing: str = ""
    recipient_addressing: str = ""
    local_read: bool = False


@dataclass
class Conversation:
    address: str
    contact_name: str | None
    messages: list[Message]


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
    Upserts `contacts` into the cache, keyed on handle, replacing each contact's numbers with
    `Contact.numbers` (a contact can carry more than one, e.g. mobile/home/work).

    :param contacts: Contacts to upsert; a no-op if empty.
    """
    if not contacts:
        return
    conn = _connect()
    try:
        conn.executemany(
            """
            INSERT INTO contacts (handle, name) VALUES (?, ?)
            ON CONFLICT(handle) DO UPDATE SET name=excluded.name
            """,
            [(c.handle, c.name) for c in contacts],
        )
        conn.executemany("DELETE FROM contact_numbers WHERE contact_handle = ?", [(c.handle,) for c in contacts])
        conn.executemany(
            """
            INSERT INTO contact_numbers (number, contact_handle) VALUES (?, ?)
            ON CONFLICT(number) DO UPDATE SET contact_handle=excluded.contact_handle
            """,
            [(number, c.handle) for c in contacts for number in c.numbers],
        )
        conn.commit()
    finally:
        conn.close()


def list_contacts() -> list[Contact]:
    """
    Lists all cached contacts, sorted by name.

    :returns: List of Contact objects; `numbers` is [] for a contact with none cached.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT c.handle, c.name, cn.number
            FROM contacts c
            LEFT JOIN contact_numbers cn ON cn.contact_handle = c.handle
            ORDER BY c.name COLLATE NOCASE, c.handle, cn.number
            """
        ).fetchall()
    finally:
        conn.close()

    contacts: list[Contact] = []
    for handle, name, number in rows:
        if not contacts or contacts[-1].handle != handle:
            contacts.append(Contact(handle=handle, name=name, numbers=[]))
        if number is not None:
            contacts[-1].numbers.append(number)
    return contacts


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


def _message_from_row(row: Sequence) -> Message:
    folder, handle, dt, sender_addressing, recipient_addressing, text, local_read = row
    return Message(
        folder=folder,
        handle=handle,
        datetime=dt,
        sender_addressing=sender_addressing,
        recipient_addressing=recipient_addressing,
        text=text,
        local_read=bool(local_read),
    )


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
    return [_message_from_row(row) for row in rows]


def list_conversations(
    addresses: list[str] | None = None, messages_per_conversation: int | None = None
) -> list[Conversation]:
    """
    Lists conversations, grouped by the messages.conversation_addressing generated column
    (recipient_addressing for sent messages, sender_addressing otherwise). Conversations are
    ordered oldest-newest-message first; each conversation's own messages are oldest-first.
    Grouping, both orderings, the per-conversation cap, and the contact-name lookup all happen in
    SQL -- Python just does one linear pass reshaping the already-ordered flat rows into
    Conversation/Message objects.

    :param addresses: Addresses to include; omit (None) for every conversation in the cache. An
        empty list matches no addresses, returning [].
    :param messages_per_conversation: Caps each conversation to its N most recent messages (still
        oldest-first within that window); omit (None) for full history. 0 drops every conversation
        from the result, since none would have any messages left to show.
    :returns: Conversations ordered by their newest message's datetime, ascending.
        `contact_name` is None if the address doesn't match a synced contact.
    """
    columns = ", ".join(_MESSAGE_COLUMNS)
    scoped_columns = ", ".join(f"s.{c}" for c in (*_MESSAGE_COLUMNS, "local_read", "conversation_addressing"))
    params: list = []

    scope_clause = ""
    if addresses is not None:
        placeholders = ", ".join("?" * len(addresses))
        scope_clause = f"WHERE conversation_addressing IN ({placeholders})"
        params.extend(addresses)

    cap_clause = ""
    if messages_per_conversation is not None:
        cap_clause = "WHERE s.recency_rank <= ?"
        params.append(messages_per_conversation)

    query = f"""
        WITH scoped AS (
            SELECT {columns}, local_read, conversation_addressing,
                   ROW_NUMBER() OVER (PARTITION BY conversation_addressing ORDER BY datetime DESC) AS recency_rank,
                   MAX(datetime) OVER (PARTITION BY conversation_addressing) AS conversation_last_datetime
            FROM messages
            {scope_clause}
        )
        SELECT {scoped_columns}, c.name
        FROM scoped s
        LEFT JOIN contact_numbers cn ON cn.number = s.conversation_addressing
        LEFT JOIN contacts c ON c.handle = cn.contact_handle
        {cap_clause}
        ORDER BY s.conversation_last_datetime ASC, s.datetime ASC
    """
    conn = _connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    conversations: list[Conversation] = []
    for *msg_fields, address, contact_name in rows:
        if not conversations or conversations[-1].address != address:
            conversations.append(Conversation(address=address, contact_name=contact_name, messages=[]))
        conversations[-1].messages.append(_message_from_row(msg_fields))
    return conversations


def clear() -> None:
    """
    Deletes the local sqlite cache file, if it exists.
    """
    _db_path().unlink(missing_ok=True)
