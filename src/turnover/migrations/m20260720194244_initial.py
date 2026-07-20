"""Creates the contacts and messages tables."""

import sqlite3


def up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE contacts (
            handle TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            number TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE messages (
            folder TEXT NOT NULL,
            handle TEXT NOT NULL,
            datetime TEXT NOT NULL,
            sender_addressing TEXT NOT NULL,
            recipient_addressing TEXT NOT NULL,
            text TEXT NOT NULL,
            local_read INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (folder, handle)
        )
        """
    )


def down(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE messages")
    conn.execute("DROP TABLE contacts")
