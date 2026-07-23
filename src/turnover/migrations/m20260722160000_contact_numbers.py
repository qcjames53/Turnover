"""Splits contacts.number into its own contact_numbers table -- a contact can carry more than one
number (mobile/home/work), which a single NOT NULL column can't represent.
"""

import sqlite3


def up(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE contact_numbers (
            number TEXT PRIMARY KEY,
            contact_handle TEXT NOT NULL REFERENCES contacts(handle)
        )
        """
    )
    conn.execute("CREATE INDEX idx_contact_numbers_contact_handle ON contact_numbers(contact_handle)")
    conn.execute(
        "INSERT INTO contact_numbers (number, contact_handle) SELECT number, handle FROM contacts WHERE number != ''"
    )
    conn.execute("ALTER TABLE contacts DROP COLUMN number")


def down(conn: sqlite3.Connection) -> None:
    # Lossy: a contact with more than one number collapses back to an arbitrary one.
    conn.execute("ALTER TABLE contacts ADD COLUMN number TEXT NOT NULL DEFAULT ''")
    conn.execute(
        """
        UPDATE contacts SET number = COALESCE(
            (SELECT number FROM contact_numbers WHERE contact_handle = contacts.handle LIMIT 1), ''
        )
        """
    )
    conn.execute("DROP INDEX idx_contact_numbers_contact_handle")
    conn.execute("DROP TABLE contact_numbers")
