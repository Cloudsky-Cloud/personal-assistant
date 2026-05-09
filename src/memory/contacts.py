import sqlite3
from pathlib import Path

from ..config import settings

_EXTRA_FIELDS = [
    "phone_mobile", "phone_work", "phone_home",
    "address_street", "address_city", "address_country",
    "company", "notes", "birthday",
]
_ALL_FIELDS = ["name", "email"] + _EXTRA_FIELDS


class ContactsDB:
    def _conn(self) -> sqlite3.Connection:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def lookup(self, name: str) -> list[dict]:
        """Return all contacts whose name contains *name* (case-insensitive)."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_ALL_FIELDS)} FROM contacts"
                " WHERE name LIKE ? LIMIT 10",
                (f"%{name}%",),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_ALL_FIELDS)} FROM contacts ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert(self, name: str, email: str, **kwargs) -> None:
        extra = {k: v for k, v in kwargs.items() if k in _EXTRA_FIELDS and v is not None}
        columns = ["name", "email"] + list(extra.keys())
        placeholders = ", ".join("?" * len(columns))
        values = [name, email] + list(extra.values())
        update_parts = ["name=excluded.name"] + [f"{k}=excluded.{k}" for k in extra]
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO contacts ({', '.join(columns)}) VALUES ({placeholders})"
                f" ON CONFLICT(email) DO UPDATE SET {', '.join(update_parts)}",
                values,
            )

    def delete(self, name: str) -> int:
        """Delete contacts matching *name* (case-insensitive). Returns rows deleted."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM contacts WHERE name LIKE ?", (f"%{name}%",)
            )
            return cur.rowcount


contacts_db = ContactsDB()
