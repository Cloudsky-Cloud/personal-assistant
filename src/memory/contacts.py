import sqlite3
from pathlib import Path
from typing import Optional

from ..config import settings


class ContactsDB:
    def _conn(self) -> sqlite3.Connection:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(settings.db_path)

    def lookup(self, name: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT name, email FROM contacts WHERE name LIKE ? LIMIT 1",
                (f"%{name}%",),
            ).fetchone()
        return {"name": row[0], "email": row[1]} if row else None

    def upsert(self, name: str, email: str):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO contacts (name, email) VALUES (?, ?)
                   ON CONFLICT(email) DO UPDATE SET name=excluded.name""",
                (name, email),
            )


contacts_db = ContactsDB()
