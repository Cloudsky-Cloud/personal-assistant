import sqlite3
from pathlib import Path

from ..config import settings


class ContactsDB:
    def _conn(self) -> sqlite3.Connection:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(settings.db_path)

    def lookup(self, name: str) -> list[dict]:
        """Return all contacts whose name contains *name* (case-insensitive)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, email FROM contacts WHERE name LIKE ? LIMIT 10",
                (f"%{name}%",),
            ).fetchall()
        return [{"name": r[0], "email": r[1]} for r in rows]

    def list_all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name, email FROM contacts ORDER BY name"
            ).fetchall()
        return [{"name": r[0], "email": r[1]} for r in rows]

    def upsert(self, name: str, email: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO contacts (name, email) VALUES (?, ?)
                   ON CONFLICT(email) DO UPDATE SET name=excluded.name""",
                (name, email),
            )

    def delete(self, name: str) -> int:
        """Delete contacts matching *name* (case-insensitive). Returns rows deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM contacts WHERE name LIKE ?", (f"%{name}%",)
            )
            return cur.rowcount


contacts_db = ContactsDB()
