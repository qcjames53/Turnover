"""Adds a generated conversation_addressing column to messages, so conversations can be grouped
directly in SQL instead of in Python: recipient_addressing for sent messages, sender_addressing
otherwise -- mirrors db.py's list_conversations.

VIRTUAL rather than STORED: SQLite can't ADD a STORED generated column to a non-empty table (it
would need to backfill it), only an empty one. VIRTUAL computes on read instead of on write, which
is irrelevant at this cache's size and still supports the index below.
"""

import sqlite3


def up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        ALTER TABLE messages ADD COLUMN conversation_addressing TEXT
        GENERATED ALWAYS AS (
            CASE WHEN folder = 'sent' THEN recipient_addressing ELSE sender_addressing END
        ) VIRTUAL
        """
    )
    conn.execute("CREATE INDEX idx_messages_conversation_addressing ON messages(conversation_addressing, datetime)")


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP INDEX idx_messages_conversation_addressing")
    conn.execute("ALTER TABLE messages DROP COLUMN conversation_addressing")
