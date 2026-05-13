import aiosqlite
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings


class Database:
    def __init__(self):
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self):
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(settings.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._run_migrations()

    async def close(self):
        if self._db:
            await self._db.close()

    async def _run_migrations(self):
        # Track which files have been applied so non-idempotent statements
        # (e.g. ALTER TABLE ADD COLUMN) are never run twice.
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS _migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await self._db.commit()

        migrations_dir = Path(__file__).parent.parent.parent / "migrations"
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            filename = sql_file.name
            async with self._db.execute(
                "SELECT 1 FROM _migrations WHERE filename = ?", (filename,)
            ) as cur:
                if await cur.fetchone():
                    continue
            await self._db.executescript(sql_file.read_text())
            await self._db.execute(
                "INSERT INTO _migrations (filename) VALUES (?)", (filename,)
            )
            await self._db.commit()

    # ── Users ──────────────────────────────────────────────────────────────

    async def upsert_user(self, telegram_id: int, username: str, first_name: str):
        await self._db.execute(
            """INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
               username=excluded.username, first_name=excluded.first_name""",
            (telegram_id, username, first_name),
        )
        await self._db.commit()

    async def get_user(self, telegram_id: int) -> Optional[dict]:
        async with self._db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_user_preferences(self, telegram_id: int) -> dict:
        user = await self.get_user(telegram_id)
        return json.loads(user["preferences"]) if user else {}

    async def set_user_preference(self, telegram_id: int, key: str, value):
        prefs = await self.get_user_preferences(telegram_id)
        prefs[key] = value
        await self._db.execute(
            "UPDATE users SET preferences = ? WHERE telegram_id = ?",
            (json.dumps(prefs), telegram_id),
        )
        await self._db.commit()

    async def get_all_user_ids(self) -> list[int]:
        async with self._db.execute("SELECT telegram_id FROM users") as cur:
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    # ── Conversations ──────────────────────────────────────────────────────

    async def save_message(
        self,
        telegram_id: int,
        role: str,
        content: str,
        tool_calls=None,
        tool_call_id: Optional[str] = None,
    ):
        await self._db.execute(
            """INSERT INTO conversations
               (telegram_id, role, content, tool_calls, tool_call_id)
               VALUES (?, ?, ?, ?, ?)""",
            (
                telegram_id,
                role,
                content,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
            ),
        )
        await self._db.commit()

    async def get_messages_since(self, since: datetime, limit: int = 2000) -> list[dict]:
        """Return all user+assistant messages across all users since a UTC datetime."""
        async with self._db.execute(
            """SELECT telegram_id, role, content, created_at
               FROM conversations
               WHERE created_at >= ? AND role IN ('user', 'assistant') AND content IS NOT NULL
               ORDER BY created_at ASC LIMIT ?""",
            (since.isoformat(), limit),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_recent_messages(self, telegram_id: int, limit: int = 30) -> list[dict]:
        async with self._db.execute(
            """SELECT role, content, tool_calls, tool_call_id, created_at
               FROM conversations WHERE telegram_id = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (telegram_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        messages = [dict(r) for r in reversed(rows)]
        for m in messages:
            if m["tool_calls"]:
                m["tool_calls"] = json.loads(m["tool_calls"])
        return messages

    # ── Tasks ──────────────────────────────────────────────────────────────

    async def save_task(
        self,
        telegram_id: int,
        title: str,
        description: str = "",
        urgency: float = 0.5,
        importance: float = 0.5,
        due_date: Optional[str] = None,
        gtasks_id: Optional[str] = None,
    ):
        priority = (urgency + importance) / 2
        await self._db.execute(
            """INSERT INTO tasks
               (telegram_id, title, description, urgency_score, importance_score,
                priority_score, due_date, gtasks_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (telegram_id, title, description, urgency, importance, priority, due_date, gtasks_id),
        )
        await self._db.commit()

    async def get_pending_tasks(self, telegram_id: int) -> list[dict]:
        async with self._db.execute(
            """SELECT * FROM tasks WHERE telegram_id = ? AND status = 'pending'
               ORDER BY priority_score DESC, created_at ASC""",
            (telegram_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_task_status(self, task_id: int, status: str):
        await self._db.execute(
            "UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, task_id),
        )
        await self._db.commit()

    async def update_task_scores(self, task_id: int, urgency: float, importance: float):
        priority = (urgency + importance) / 2
        await self._db.execute(
            """UPDATE tasks SET urgency_score=?, importance_score=?, priority_score=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (urgency, importance, priority, task_id),
        )
        await self._db.commit()

    # ── Energy scores ──────────────────────────────────────────────────────

    async def save_energy_score(
        self,
        date_str: str,
        score: int,
        level: str,
        sleep_hours=None,
        sleep_minutes=None,
        heart_rate_bpm=None,
        steps=None,
        active_minutes=None,
    ):
        await self._db.execute(
            """INSERT INTO energy_scores
               (date, score, level, sleep_hours, sleep_minutes, heart_rate_bpm, steps, active_minutes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               score=excluded.score, level=excluded.level,
               sleep_hours=excluded.sleep_hours, sleep_minutes=excluded.sleep_minutes,
               heart_rate_bpm=excluded.heart_rate_bpm, steps=excluded.steps,
               active_minutes=excluded.active_minutes""",
            (date_str, score, level, sleep_hours, sleep_minutes, heart_rate_bpm, steps, active_minutes),
        )
        await self._db.commit()

    async def get_energy_scores(self, days: int = 7) -> list[dict]:
        async with self._db.execute(
            """SELECT date, score, level, sleep_hours, sleep_minutes, heart_rate_bpm, steps, active_minutes
               FROM energy_scores ORDER BY date DESC LIMIT ?""",
            (days,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get_latest_energy_score(self) -> Optional[dict]:
        async with self._db.execute(
            """SELECT date, score, level, sleep_hours, sleep_minutes, heart_rate_bpm, steps, active_minutes
               FROM energy_scores ORDER BY date DESC LIMIT 1"""
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def save_sleep_score(
        self,
        date_str: str,
        sleep_score: int,
        sleep_label: str,
        in_bed_minutes: Optional[int] = None,
    ):
        await self._db.execute(
            """INSERT INTO energy_scores (date, score, level, sleep_score, sleep_label, in_bed_minutes)
               VALUES (?, 0, 'unknown', ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               sleep_score=excluded.sleep_score,
               sleep_label=excluded.sleep_label,
               in_bed_minutes=excluded.in_bed_minutes""",
            (date_str, sleep_score, sleep_label, in_bed_minutes),
        )
        await self._db.commit()

    async def get_sleep_score_by_date(self, date_str: str) -> Optional[dict]:
        async with self._db.execute(
            """SELECT date, sleep_score, sleep_label, in_bed_minutes
               FROM energy_scores WHERE date = ?""",
            (date_str,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    # ── Briefings ──────────────────────────────────────────────────────────

    async def save_briefing(self, telegram_id: int, content: str):
        await self._db.execute(
            "INSERT INTO briefing_history (telegram_id, content) VALUES (?, ?)",
            (telegram_id, content),
        )
        await self._db.commit()


db = Database()
