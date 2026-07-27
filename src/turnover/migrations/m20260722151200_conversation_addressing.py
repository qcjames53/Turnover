"""Adds a generated conversation_addressing column to messages, so conversations can be grouped"""

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
