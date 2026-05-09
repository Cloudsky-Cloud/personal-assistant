import sqlite3
from pathlib import Path
from typing import Optional

from ..config import settings


class ProjectsDB:
    def _conn(self) -> sqlite3.Connection:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(settings.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _find_id(self, conn: sqlite3.Connection, name: str) -> Optional[int]:
        row = conn.execute(
            "SELECT id FROM projects WHERE name LIKE ? LIMIT 1", (f"%{name}%",)
        ).fetchone()
        return row["id"] if row else None

    def _project_dict(self, row: sqlite3.Row) -> dict:
        return {
            "name": row["name"],
            "status": row["status"],
            "due_date": row["due_date"],
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create(
        self,
        name: str,
        status: str = "active",
        due_date: Optional[str] = None,
        description: str = "",
    ) -> dict:
        with self._conn() as conn:
            try:
                conn.execute(
                    "INSERT INTO projects (name, status, due_date, description) VALUES (?, ?, ?, ?)",
                    (name, status, due_date, description),
                )
                row = conn.execute(
                    "SELECT name, status, due_date, description, created_at, updated_at"
                    " FROM projects WHERE name = ?",
                    (name,),
                ).fetchone()
                return {"status": "created", **self._project_dict(row)}
            except sqlite3.IntegrityError:
                return {"error": f"A project named '{name}' already exists."}

    def update(self, name: str, **fields) -> dict:
        allowed = {"name", "status", "due_date", "description"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not updates:
            return {"error": "No valid fields to update."}
        with self._conn() as conn:
            project_id = self._find_id(conn, name)
            if project_id is None:
                return {"error": f"No project found matching '{name}'."}
            set_clause = ", ".join(f"{k}=?" for k in updates) + ", updated_at=CURRENT_TIMESTAMP"
            conn.execute(
                f"UPDATE projects SET {set_clause} WHERE id=?",
                [*updates.values(), project_id],
            )
            row = conn.execute(
                "SELECT name, status, due_date, description, created_at, updated_at"
                " FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            return {"status": "updated", **self._project_dict(row)}

    def list_projects(
        self,
        status: Optional[str] = None,
        due_before: Optional[str] = None,
    ) -> list[dict]:
        conditions, params = [], []
        if status:
            conditions.append("p.status = ?")
            params.append(status)
        if due_before:
            conditions.append("p.due_date IS NOT NULL AND p.due_date <= ?")
            params.append(due_before)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        query = f"""
            SELECT p.name, p.status, p.due_date, p.description,
                   p.created_at, p.updated_at, COUNT(n.id) AS note_count
            FROM projects p
            LEFT JOIN project_notes n ON p.id = n.project_id
            {where}
            GROUP BY p.id
            ORDER BY p.due_date IS NULL, p.due_date ASC, p.name ASC
        """
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {**self._project_dict(r), "note_count": r["note_count"]}
            for r in rows
        ]

    def delete(self, name: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM projects WHERE name LIKE ?", (f"%{name}%",)
            )
            return cur.rowcount

    # ── Notes ─────────────────────────────────────────────────────────────────

    def add_note(self, project_name: str, content: str) -> dict:
        with self._conn() as conn:
            project_id = self._find_id(conn, project_name)
            if project_id is None:
                return {"error": f"No project found matching '{project_name}'."}
            conn.execute(
                "INSERT INTO project_notes (project_id, content) VALUES (?, ?)",
                (project_id, content),
            )
            proj_name = conn.execute(
                "SELECT name FROM projects WHERE id = ?", (project_id,)
            ).fetchone()["name"]
            return {"status": "note_added", "project": proj_name}

    def get_notes(self, project_name: str) -> dict:
        with self._conn() as conn:
            project_id = self._find_id(conn, project_name)
            if project_id is None:
                return {"error": f"No project found matching '{project_name}'."}
            proj = conn.execute(
                "SELECT name, status, due_date, description, created_at, updated_at"
                " FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            notes = conn.execute(
                "SELECT content, created_at FROM project_notes"
                " WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return {
            **self._project_dict(proj),
            "notes": [{"content": n["content"], "created_at": n["created_at"]} for n in notes],
        }

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str) -> list[dict]:
        pattern = f"%{query}%"
        sql = """
            SELECT p.name, p.status, p.due_date, p.description,
                   p.created_at, p.updated_at, COUNT(n.id) AS note_count
            FROM projects p
            LEFT JOIN project_notes n ON p.id = n.project_id
            WHERE p.name LIKE ? OR p.description LIKE ?
               OR EXISTS (
                   SELECT 1 FROM project_notes pn
                   WHERE pn.project_id = p.id AND pn.content LIKE ?
               )
            GROUP BY p.id
            ORDER BY p.name ASC
        """
        with self._conn() as conn:
            rows = conn.execute(sql, (pattern, pattern, pattern)).fetchall()
        return [
            {**self._project_dict(r), "note_count": r["note_count"]}
            for r in rows
        ]


projects_db = ProjectsDB()
