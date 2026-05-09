# Personal Assistant Telegram Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade personal assistant Telegram bot powered by Claude claude-sonnet-4-6 with persistent SQLite + ChromaDB memory, Google Workspace integration (Gmail, Calendar, Drive, Tasks), voice transcription, daily briefings, proactive reminders, and a task prioritization engine.

**Architecture:** The bot runs as an async Python 3.12 application in Docker. `python-telegram-bot` v20 handles Telegram; the Anthropic SDK drives Claude with full tool use for all Google integrations. Google APIs (Gmail, Calendar, Drive) are wrapped as Claude tools via `google-api-python-client` — this is functionally MCP-equivalent. SQLite (aiosqlite) stores structured data; ChromaDB handles semantic vector search over conversation history. APScheduler drives daily briefings and proactive reminders. All components are wired together in `src/main.py`.

**Tech Stack:** Python 3.12, python-telegram-bot 20.7, anthropic ≥0.40, google-api-python-client 2.130, google-auth-oauthlib 1.2, aiosqlite 0.20, chromadb 0.5, sentence-transformers 2.7, faster-whisper 1.0, APScheduler 3.10, pydantic-settings 2.x, pytest 8.x, pytest-asyncio 0.23

---

## File Structure

```
personal-assistant/
├── Dockerfile
├── docker-compose.yml
├── .env.template
├── .gitignore
├── pyproject.toml
├── setup_auth.py                       # One-time Google OAuth2 CLI tool
├── README.md
├── credentials/                        # Volume-mounted Google credentials
│   └── google_credentials.json         # Downloaded from Google Cloud Console
├── data/                               # Persistent volume
│   ├── assistant.db                    # SQLite database
│   ├── chroma/                         # ChromaDB persistent storage
│   ├── google_token.json               # OAuth2 token (written by setup_auth.py)
│   └── whisper/                        # Whisper model cache
├── migrations/
│   └── 001_initial.sql
├── src/
│   ├── __init__.py
│   ├── main.py                         # Entry point: wires all components
│   ├── config.py                       # Pydantic settings loaded from .env
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── claude_client.py            # Anthropic client + tool-use loop
│   │   └── tools.py                    # All tool schemas + dispatch registry
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── telegram_bot.py             # Bot lifecycle + handler registration
│   │   └── handlers/
│   │       ├── __init__.py
│   │       ├── commands.py             # /start /briefing /tasks /help /auth
│   │       ├── messages.py             # Text message → Claude pipeline
│   │       └── voice.py                # Voice OGG download + transcription
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── google_auth.py              # Shared OAuth2 credential builder
│   │   ├── gmail.py                    # Gmail read/search/label
│   │   ├── gcalendar.py                # Calendar list/create/search events
│   │   ├── gdrive.py                   # Drive search/list/read metadata
│   │   └── gtasks.py                   # Tasks CRUD + list management
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── database.py                 # aiosqlite manager + migration runner
│   │   ├── vector_store.py             # ChromaDB client + upsert/search
│   │   ├── conversation.py             # Per-user conversation window manager
│   │   └── context_retriever.py        # Semantic context retrieval
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── briefing.py                 # Daily morning briefing job
│   │   └── reminders.py                # Proactive calendar/task reminder job
│   ├── tasks/
│   │   ├── __init__.py
│   │   └── prioritizer.py              # Eisenhower matrix + urgency scorer
│   └── utils/
│       ├── __init__.py
│       ├── transcription.py            # faster-whisper OGG→text
│       └── formatting.py               # Telegram MarkdownV2 helpers
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_database.py
    ├── test_vector_store.py
    ├── test_claude_client.py
    ├── test_prioritizer.py
    ├── test_gmail.py
    ├── test_gcalendar.py
    ├── test_gtasks.py
    └── test_handlers.py
```

---

## Task 1: Project Scaffold (Docker, dependencies, config template)

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `.env.template`
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `README.md` _(brief setup guide)_

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "personal-assistant"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = [
    "python-telegram-bot==20.7",
    "anthropic>=0.40.0",
    "google-api-python-client==2.130.0",
    "google-auth-httplib2==0.2.0",
    "google-auth-oauthlib==1.2.0",
    "aiosqlite==0.20.0",
    "chromadb==0.5.23",
    "sentence-transformers==2.7.0",
    "faster-whisper==1.0.3",
    "APScheduler==3.10.4",
    "pydantic-settings==2.3.4",
    "pydantic>=2.7",
    "httpx>=0.27",
    "python-dateutil==2.9.0",
    "pytz==2024.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.14",
    "freezegun>=1.5",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Pre-download whisper model so container starts fast
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8', download_root='/app/data/whisper')"

COPY . .

CMD ["python", "-m", "src.main"]
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
version: "3.9"

services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./credentials:/app/credentials:ro
    environment:
      - PYTHONUNBUFFERED=1
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 4: Create `.env.template`**

```dotenv
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_ALLOWED_USERS=123456789,987654321   # comma-separated Telegram user IDs

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# Google OAuth (credentials file mounted as volume)
GOOGLE_CREDENTIALS_FILE=/app/credentials/google_credentials.json
GOOGLE_TOKEN_FILE=/app/data/google_token.json

# Paths (defaults match docker-compose volumes)
DB_PATH=/app/data/assistant.db
CHROMA_PATH=/app/data/chroma
WHISPER_MODEL_PATH=/app/data/whisper

# Scheduler
BRIEFING_TIME=08:00         # HH:MM in the timezone below
TIMEZONE=Europe/London      # pytz timezone string

# Optional tuning
CLAUDE_MODEL=claude-sonnet-4-6
WHISPER_MODEL=base
CONVERSATION_WINDOW=30      # messages kept in context
```

- [ ] **Step 5: Create `.gitignore`**

```gitignore
.env
data/
credentials/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.venv/
```

- [ ] **Step 6: Create `README.md`**

```markdown
# Personal Assistant Bot

## Setup

1. **Copy env template**
   ```bash
   cp .env.template .env
   # Edit .env with your tokens
   ```

2. **Place Google credentials**
   Download OAuth2 credentials from Google Cloud Console (Desktop app type).
   Save as `credentials/google_credentials.json`.
   Enable APIs: Gmail, Calendar, Drive, Tasks.

3. **Run Google OAuth flow (one-time)**
   ```bash
   docker-compose run --rm bot python setup_auth.py
   ```
   Follow the URL printed to the console. Token saved to `data/google_token.json`.

4. **Start bot**
   ```bash
   docker-compose up -d
   ```

## Commands
- `/start` — Welcome message
- `/briefing` — Trigger daily briefing now
- `/tasks` — Show prioritized task list
- `/help` — Show all commands
```

- [ ] **Step 7: Commit**

```bash
git init
git add pyproject.toml Dockerfile docker-compose.yml .env.template .gitignore README.md
git commit -m "chore: project scaffold, Docker setup, and dependencies"
```

---

## Task 2: Configuration

**Files:**
- Create: `src/__init__.py` _(empty)_
- Create: `src/config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
from src.config import Settings

def test_settings_loads_required_fields(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111,222")
    s = Settings()
    assert s.telegram_bot_token == "test_token"
    assert s.anthropic_api_key == "sk-ant-test"
    assert s.telegram_allowed_users == [111, 222]
    assert s.claude_model == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_config.py -v
# Expected: ImportError or ModuleNotFoundError
```

- [ ] **Step 3: Create `src/__init__.py`** (empty file)

- [ ] **Step 4: Implement `src/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str
    telegram_allowed_users: list[int] = []

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # Google
    google_credentials_file: str = "/app/credentials/google_credentials.json"
    google_token_file: str = "/app/data/google_token.json"

    # Storage
    db_path: str = "/app/data/assistant.db"
    chroma_path: str = "/app/data/chroma"
    whisper_model_path: str = "/app/data/whisper"

    # Scheduler
    briefing_time: str = "08:00"
    timezone: str = "UTC"

    # Tuning
    whisper_model: str = "base"
    conversation_window: int = 30

    @field_validator("telegram_allowed_users", mode="before")
    @classmethod
    def parse_allowed_users(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


settings = Settings()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_config.py -v
# Expected: PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/__init__.py src/config.py tests/test_config.py
git commit -m "feat: pydantic-settings configuration"
```

---

## Task 3: Database Layer

**Files:**
- Create: `migrations/001_initial.sql`
- Create: `src/memory/__init__.py` _(empty)_
- Create: `src/memory/database.py`
- Test: `tests/test_database.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_database.py
import pytest
import pytest_asyncio
import tempfile
import os
from unittest.mock import patch

@pytest_asyncio.fixture
async def db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        with patch("src.memory.database.settings") as mock_settings:
            mock_settings.db_path = db_path
            from src.memory.database import Database
            database = Database()
            await database.connect()
            yield database
            await database.close()

@pytest.mark.asyncio
async def test_upsert_and_get_user(db):
    await db.upsert_user(12345, "testuser", "Test")
    user = await db.get_user(12345)
    assert user["telegram_id"] == 12345
    assert user["username"] == "testuser"

@pytest.mark.asyncio
async def test_save_and_get_messages(db):
    await db.upsert_user(12345, "u", "U")
    await db.save_message(12345, "user", "hello world")
    await db.save_message(12345, "assistant", "Hi there!")
    messages = await db.get_recent_messages(12345)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"

@pytest.mark.asyncio
async def test_save_and_get_tasks(db):
    await db.upsert_user(12345, "u", "U")
    await db.save_task(12345, "Buy groceries", "Milk, bread", urgency=0.8, importance=0.6)
    tasks = await db.get_pending_tasks(12345)
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Buy groceries"
    assert tasks[0]["priority_score"] == pytest.approx(0.7)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_database.py -v
# Expected: ImportError
```

- [ ] **Step 3: Create `migrations/001_initial.sql`**

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    preferences TEXT DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'tool_result')),
    content TEXT NOT NULL,
    tool_calls TEXT,
    tool_call_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    urgency_score REAL DEFAULT 0.5,
    importance_score REAL DEFAULT 0.5,
    priority_score REAL DEFAULT 0.5,
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    gtasks_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS briefing_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_tid ON conversations(telegram_id);
CREATE INDEX IF NOT EXISTS idx_conv_ts  ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_tid ON tasks(telegram_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
```

- [ ] **Step 4: Implement `src/memory/database.py`**

```python
import aiosqlite
import json
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
        sql_path = Path(__file__).parent.parent.parent / "migrations" / "001_initial.sql"
        await self._db.executescript(sql_path.read_text())
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

    async def get_recent_messages(self, telegram_id: int, limit: int = 30) -> list[dict]:
        async with self._db.execute(
            """SELECT role, content, tool_calls, tool_call_id, created_at
               FROM conversations WHERE telegram_id = ?
               ORDER BY created_at DESC LIMIT ?""",
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

    # ── Briefings ──────────────────────────────────────────────────────────

    async def save_briefing(self, telegram_id: int, content: str):
        await self._db.execute(
            "INSERT INTO briefing_history (telegram_id, content) VALUES (?, ?)",
            (telegram_id, content),
        )
        await self._db.commit()


db = Database()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_database.py -v
# Expected: 3 PASS
```

- [ ] **Step 6: Commit**

```bash
git add migrations/ src/memory/__init__.py src/memory/database.py tests/test_database.py
git commit -m "feat: SQLite database layer with aiosqlite"
```

---

## Task 4: Vector Memory (ChromaDB)

**Files:**
- Create: `src/memory/vector_store.py`
- Create: `src/memory/context_retriever.py`
- Test: `tests/test_vector_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_vector_store.py
import pytest
import tempfile
import os
from unittest.mock import patch

@pytest.fixture
def vector_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("src.memory.vector_store.settings") as mock_s:
            mock_s.chroma_path = tmpdir
            from src.memory.vector_store import VectorStore
            store = VectorStore()
            store.init()
            yield store

def test_upsert_and_query(vector_store):
    vector_store.upsert_memory(
        doc_id="msg_1",
        text="I prefer meetings before noon",
        metadata={"telegram_id": 111, "type": "preference"},
    )
    results = vector_store.query(
        text="when do you like meetings",
        telegram_id=111,
        n_results=1,
    )
    assert len(results) == 1
    assert "noon" in results[0]["text"]

def test_query_filters_by_user(vector_store):
    vector_store.upsert_memory("m1", "user A likes coffee", {"telegram_id": 1, "type": "pref"})
    vector_store.upsert_memory("m2", "user B likes tea", {"telegram_id": 2, "type": "pref"})
    results = vector_store.query("drinks", telegram_id=1, n_results=5)
    assert all(r["metadata"]["telegram_id"] == 1 for r in results)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_vector_store.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/memory/vector_store.py`**

```python
import chromadb
from chromadb.utils import embedding_functions
from pathlib import Path

from ..config import settings


class VectorStore:
    def __init__(self):
        self._client = None
        self._collection = None

    def init(self):
        Path(settings.chroma_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        self._collection = self._client.get_or_create_collection(
            name="assistant_memory",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert_memory(self, doc_id: str, text: str, metadata: dict):
        metadata = {k: v for k, v in metadata.items() if v is not None}
        self._collection.upsert(ids=[doc_id], documents=[text], metadatas=[metadata])

    def query(
        self,
        text: str,
        telegram_id: int,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        filter_clause = {"telegram_id": telegram_id}
        if where:
            filter_clause.update(where)
        try:
            results = self._collection.query(
                query_texts=[text],
                n_results=n_results,
                where=filter_clause,
            )
        except Exception:
            return []
        output = []
        for i, doc in enumerate(results["documents"][0]):
            output.append(
                {
                    "text": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                }
            )
        return output

    def delete_by_user(self, telegram_id: int):
        self._collection.delete(where={"telegram_id": telegram_id})


vector_store = VectorStore()
```

- [ ] **Step 4: Implement `src/memory/context_retriever.py`**

```python
from .vector_store import vector_store
from .database import db


class ContextRetriever:
    async def store_message(self, telegram_id: int, role: str, text: str, msg_id: str):
        vector_store.upsert_memory(
            doc_id=f"msg_{msg_id}",
            text=text,
            metadata={"telegram_id": telegram_id, "role": role, "type": "message"},
        )

    async def store_preference(self, telegram_id: int, preference: str, pref_id: str):
        vector_store.upsert_memory(
            doc_id=f"pref_{pref_id}",
            text=preference,
            metadata={"telegram_id": telegram_id, "type": "preference"},
        )

    async def get_relevant_context(self, telegram_id: int, query: str, n: int = 5) -> str:
        results = vector_store.query(text=query, telegram_id=telegram_id, n_results=n)
        if not results:
            return ""
        lines = [f"- {r['text']}" for r in results if r["distance"] < 0.8]
        return "\n".join(lines)


context_retriever = ContextRetriever()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_vector_store.py -v
# Expected: 2 PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/memory/vector_store.py src/memory/context_retriever.py tests/test_vector_store.py
git commit -m "feat: ChromaDB vector memory with sentence-transformers"
```

---

## Task 5: Google Auth + Google Tasks Integration

**Files:**
- Create: `src/integrations/__init__.py` _(empty)_
- Create: `src/integrations/google_auth.py`
- Create: `src/integrations/gtasks.py`
- Create: `setup_auth.py`
- Test: `tests/test_gtasks.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gtasks.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.fixture
def mock_service():
    svc = MagicMock()
    tasklists = MagicMock()
    tasklists.list.return_value.execute.return_value = {
        "items": [{"id": "list1", "title": "My Tasks"}]
    }
    tasks_resource = MagicMock()
    tasks_resource.list.return_value.execute.return_value = {
        "items": [
            {"id": "t1", "title": "Buy milk", "status": "needsAction", "notes": ""},
        ]
    }
    tasks_resource.insert.return_value.execute.return_value = {
        "id": "t2", "title": "New task"
    }
    svc.tasklists.return_value = tasklists
    svc.tasks.return_value = tasks_resource
    return svc

def test_list_tasks(mock_service):
    with patch("src.integrations.gtasks.build_google_service", return_value=mock_service):
        from src.integrations.gtasks import GoogleTasks
        gt = GoogleTasks()
        result = gt.list_tasks()
        assert len(result) == 1
        assert result[0]["title"] == "Buy milk"

def test_create_task(mock_service):
    with patch("src.integrations.gtasks.build_google_service", return_value=mock_service):
        from src.integrations.gtasks import GoogleTasks
        gt = GoogleTasks()
        result = gt.create_task("New task", notes="details")
        assert result["id"] == "t2"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_gtasks.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/integrations/google_auth.py`**

```python
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from ..config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
]


def get_credentials() -> Credentials:
    token_path = Path(settings.google_token_file)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds

    if not creds or not creds.valid:
        raise RuntimeError(
            f"Google credentials not found or invalid. "
            f"Run: docker-compose run --rm bot python setup_auth.py"
        )
    return creds


def build_google_service(api_name: str, api_version: str):
    creds = get_credentials()
    return build(api_name, api_version, credentials=creds)
```

- [ ] **Step 4: Implement `src/integrations/gtasks.py`**

```python
from typing import Optional
from .google_auth import build_google_service


class GoogleTasks:
    def __init__(self):
        self._service = None

    def _get_service(self):
        if self._service is None:
            self._service = build_google_service("tasks", "v1")
        return self._service

    def _get_default_list_id(self) -> str:
        svc = self._get_service()
        result = svc.tasklists().list(maxResults=1).execute()
        items = result.get("items", [])
        return items[0]["id"] if items else "@default"

    def list_tasks(self, max_results: int = 20, show_completed: bool = False) -> list[dict]:
        svc = self._get_service()
        list_id = self._get_default_list_id()
        result = svc.tasks().list(
            tasklist=list_id,
            maxResults=max_results,
            showCompleted=show_completed,
            showHidden=False,
        ).execute()
        return [
            {
                "id": t.get("id"),
                "title": t.get("title", ""),
                "notes": t.get("notes", ""),
                "status": t.get("status"),
                "due": t.get("due"),
            }
            for t in result.get("items", [])
        ]

    def create_task(self, title: str, notes: str = "", due: Optional[str] = None) -> dict:
        svc = self._get_service()
        list_id = self._get_default_list_id()
        body: dict = {"title": title, "notes": notes}
        if due:
            body["due"] = due
        return svc.tasks().insert(tasklist=list_id, body=body).execute()

    def complete_task(self, task_id: str) -> dict:
        svc = self._get_service()
        list_id = self._get_default_list_id()
        task = svc.tasks().get(tasklist=list_id, task=task_id).execute()
        task["status"] = "completed"
        return svc.tasks().update(tasklist=list_id, task=task_id, body=task).execute()

    def delete_task(self, task_id: str):
        svc = self._get_service()
        list_id = self._get_default_list_id()
        svc.tasks().delete(tasklist=list_id, task=task_id).execute()


gtasks = GoogleTasks()
```

- [ ] **Step 5: Create `setup_auth.py`** (one-time OAuth flow, run outside Docker or via `docker-compose run`)

```python
#!/usr/bin/env python3
"""Run once to authorize Google APIs. Saves token to data/google_token.json."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
]

def main():
    credentials_file = Path("credentials/google_credentials.json")
    token_file = Path("data/google_token.json")
    token_file.parent.mkdir(parents=True, exist_ok=True)

    if not credentials_file.exists():
        print(f"ERROR: {credentials_file} not found.")
        print("Download OAuth2 credentials from Google Cloud Console (Desktop app type).")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json())
    print(f"Token saved to {token_file}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_gtasks.py -v
# Expected: 2 PASS
```

- [ ] **Step 7: Commit**

```bash
git add src/integrations/__init__.py src/integrations/google_auth.py \
        src/integrations/gtasks.py setup_auth.py tests/test_gtasks.py
git commit -m "feat: Google Tasks integration + OAuth2 auth helper"
```

---

## Task 6: Gmail Integration

**Files:**
- Create: `src/integrations/gmail.py`
- Test: `tests/test_gmail.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gmail.py
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_gmail_service():
    svc = MagicMock()
    messages_res = MagicMock()
    messages_res.list.return_value.execute.return_value = {
        "messages": [{"id": "msg1", "threadId": "t1"}]
    }
    messages_res.get.return_value.execute.return_value = {
        "id": "msg1",
        "snippet": "Hello from test",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test Subject"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "Date", "value": "Thu, 1 Jan 2026 10:00:00 +0000"},
            ],
            "body": {"data": "SGVsbG8gV29ybGQ="},  # base64 "Hello World"
        },
        "labelIds": ["INBOX", "UNREAD"],
    }
    svc.users.return_value.messages.return_value = messages_res
    return svc

def test_list_emails(mock_gmail_service):
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        emails = g.list_unread(max_results=5)
        assert len(emails) == 1
        assert emails[0]["subject"] == "Test Subject"
        assert emails[0]["from"] == "sender@example.com"

def test_search_emails(mock_gmail_service):
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        results = g.search("from:sender@example.com")
        assert len(results) == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_gmail.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/integrations/gmail.py`**

```python
import base64
from email import message_from_bytes
from typing import Optional
from .google_auth import build_google_service


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
    return ""


def _extract_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


class Gmail:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("gmail", "v1")
        return self._service

    def _fetch_message(self, msg_id: str) -> dict:
        raw = self._svc().users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        headers = raw["payload"].get("headers", [])
        return {
            "id": raw["id"],
            "subject": _extract_header(headers, "Subject"),
            "from": _extract_header(headers, "From"),
            "date": _extract_header(headers, "Date"),
            "snippet": raw.get("snippet", ""),
            "body": _decode_body(raw["payload"])[:2000],
            "labels": raw.get("labelIds", []),
        }

    def list_unread(self, max_results: int = 10) -> list[dict]:
        res = self._svc().users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        return [self._fetch_message(m["id"]) for m in res.get("messages", [])]

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        res = self._svc().users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return [self._fetch_message(m["id"]) for m in res.get("messages", [])]

    def mark_read(self, msg_id: str):
        self._svc().users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

    def label_message(self, msg_id: str, label_name: str):
        labels = self._svc().users().labels().list(userId="me").execute()
        label_id = next(
            (l["id"] for l in labels.get("labels", []) if l["name"] == label_name),
            None,
        )
        if label_id:
            self._svc().users().messages().modify(
                userId="me", id=msg_id, body={"addLabelIds": [label_id]}
            ).execute()


gmail = Gmail()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_gmail.py -v
# Expected: 2 PASS
```

- [ ] **Step 5: Commit**

```bash
git add src/integrations/gmail.py tests/test_gmail.py
git commit -m "feat: Gmail integration (list unread, search, label)"
```

---

## Task 7: Google Calendar + Drive Integrations

**Files:**
- Create: `src/integrations/gcalendar.py`
- Create: `src/integrations/gdrive.py`
- Test: `tests/test_gcalendar.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gcalendar.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

@pytest.fixture
def mock_cal_service():
    svc = MagicMock()
    events_res = MagicMock()
    events_res.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt1",
                "summary": "Team standup",
                "start": {"dateTime": "2026-05-08T09:00:00Z"},
                "end": {"dateTime": "2026-05-08T09:30:00Z"},
                "description": "",
                "location": "",
                "attendees": [],
            }
        ]
    }
    events_res.insert.return_value.execute.return_value = {"id": "evt2", "summary": "New event"}
    svc.events.return_value = events_res
    return svc

def test_list_events(mock_cal_service):
    with patch("src.integrations.gcalendar.build_google_service", return_value=mock_cal_service):
        from src.integrations.gcalendar import GoogleCalendar
        cal = GoogleCalendar()
        events = cal.list_events(days=1)
        assert len(events) == 1
        assert events[0]["summary"] == "Team standup"

def test_create_event(mock_cal_service):
    with patch("src.integrations.gcalendar.build_google_service", return_value=mock_cal_service):
        from src.integrations.gcalendar import GoogleCalendar
        cal = GoogleCalendar()
        result = cal.create_event("New event", "2026-05-09T10:00:00Z", "2026-05-09T11:00:00Z")
        assert result["id"] == "evt2"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_gcalendar.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/integrations/gcalendar.py`**

```python
from datetime import datetime, timezone, timedelta
from typing import Optional
from .google_auth import build_google_service


class GoogleCalendar:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("calendar", "v3")
        return self._service

    def list_events(self, days: int = 7, calendar_id: str = "primary") -> list[dict]:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)
        res = self._svc().events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "No title"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
                "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
                "description": e.get("description", ""),
                "location": e.get("location", ""),
                "attendees": [a.get("email") for a in e.get("attendees", [])],
            }
            for e in res.get("items", [])
        ]

    def create_event(
        self,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: Optional[list[str]] = None,
        calendar_id: str = "primary",
    ) -> dict:
        body: dict = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]
        return self._svc().events().insert(calendarId=calendar_id, body=body).execute()

    def search_events(self, query: str, days: int = 30) -> list[dict]:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)
        res = self._svc().events().list(
            calendarId="primary",
            q=query,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "No title"),
                "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            }
            for e in res.get("items", [])
        ]


gcalendar = GoogleCalendar()
```

- [ ] **Step 4: Implement `src/integrations/gdrive.py`**

```python
from .google_auth import build_google_service


class GoogleDrive:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("drive", "v3")
        return self._service

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        res = self._svc().files().list(
            q=query,
            pageSize=max_results,
            fields="files(id,name,mimeType,webViewLink,modifiedTime,size)",
        ).execute()
        return [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "type": f.get("mimeType"),
                "link": f.get("webViewLink"),
                "modified": f.get("modifiedTime"),
            }
            for f in res.get("files", [])
        ]

    def list_recent(self, max_results: int = 10) -> list[dict]:
        return self.search(
            query="trashed=false",
            max_results=max_results,
        )

    def get_file_metadata(self, file_id: str) -> dict:
        f = self._svc().files().get(
            fileId=file_id,
            fields="id,name,mimeType,webViewLink,modifiedTime,size,description",
        ).execute()
        return {
            "id": f.get("id"),
            "name": f.get("name"),
            "type": f.get("mimeType"),
            "link": f.get("webViewLink"),
            "modified": f.get("modifiedTime"),
            "description": f.get("description", ""),
        }


gdrive = GoogleDrive()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_gcalendar.py -v
# Expected: 2 PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/integrations/gcalendar.py src/integrations/gdrive.py tests/test_gcalendar.py
git commit -m "feat: Google Calendar and Drive integrations"
```

---

## Task 8: Task Prioritization Engine

**Files:**
- Create: `src/tasks/__init__.py` _(empty)_
- Create: `src/tasks/prioritizer.py`
- Test: `tests/test_prioritizer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_prioritizer.py
import pytest
from src.tasks.prioritizer import Prioritizer, TaskScore

def test_urgent_important_gets_high_score():
    p = Prioritizer()
    score = p.score(
        title="Fix production outage",
        description="Server is down, users cannot access",
        due_in_hours=2,
    )
    assert score.urgency > 0.8
    assert score.importance > 0.7
    assert score.quadrant == "do_now"

def test_not_urgent_not_important_gets_low():
    p = Prioritizer()
    score = p.score(
        title="Reorganize bookmarks",
        description="Sort browser bookmarks into folders",
        due_in_hours=None,
    )
    assert score.urgency < 0.4
    assert score.quadrant == "eliminate"

def test_due_soon_boosts_urgency():
    p = Prioritizer()
    score_soon = p.score("Meeting prep", "", due_in_hours=1)
    score_later = p.score("Meeting prep", "", due_in_hours=72)
    assert score_soon.urgency > score_later.urgency

def test_score_task_list_sorts_by_priority():
    p = Prioritizer()
    tasks = [
        {"title": "Fix outage", "description": "Critical", "due_in_hours": 1},
        {"title": "Archive emails", "description": "Low priority", "due_in_hours": None},
        {"title": "Prepare report", "description": "For board meeting", "due_in_hours": 24},
    ]
    scored = p.score_list(tasks)
    assert scored[0]["title"] == "Fix outage"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_prioritizer.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/tasks/prioritizer.py`**

The importance heuristics use keyword matching on title + description. Urgency is driven by due-date proximity plus urgency keywords.

```python
import re
from dataclasses import dataclass
from typing import Optional


_URGENCY_KEYWORDS = {
    "critical": 0.9, "urgent": 0.9, "asap": 0.9, "emergency": 1.0,
    "outage": 0.9, "down": 0.8, "broken": 0.8, "deadline": 0.75,
    "today": 0.8, "overdue": 0.95, "immediate": 0.9,
}

_IMPORTANCE_KEYWORDS = {
    "revenue": 0.9, "client": 0.85, "customer": 0.85, "board": 0.9,
    "boss": 0.85, "ceo": 0.9, "production": 0.85, "outage": 0.9,
    "health": 0.85, "security": 0.85, "legal": 0.9, "contract": 0.8,
    "launch": 0.85, "release": 0.8, "interview": 0.75,
}

_LOW_IMPORTANCE_KEYWORDS = {
    "bookmark": -0.3, "reorganize": -0.2, "clean up": -0.2,
    "someday": -0.3, "nice to have": -0.4, "optional": -0.3,
}


@dataclass
class TaskScore:
    urgency: float      # 0.0 → 1.0
    importance: float   # 0.0 → 1.0
    priority: float     # weighted composite
    quadrant: str       # do_now | schedule | delegate | eliminate


class Prioritizer:
    def score(
        self,
        title: str,
        description: str,
        due_in_hours: Optional[float] = None,
    ) -> TaskScore:
        text = f"{title} {description}".lower()

        urgency = self._keyword_score(text, _URGENCY_KEYWORDS, base=0.3)
        if due_in_hours is not None:
            urgency = max(urgency, self._due_urgency(due_in_hours))

        importance = self._keyword_score(text, _IMPORTANCE_KEYWORDS, base=0.4)
        for kw, delta in _LOW_IMPORTANCE_KEYWORDS.items():
            if kw in text:
                importance = max(0.05, importance + delta)

        urgency = min(1.0, max(0.0, urgency))
        importance = min(1.0, max(0.0, importance))
        priority = 0.5 * urgency + 0.5 * importance
        quadrant = self._quadrant(urgency, importance)
        return TaskScore(urgency=urgency, importance=importance, priority=priority, quadrant=quadrant)

    def score_list(self, tasks: list[dict]) -> list[dict]:
        results = []
        for t in tasks:
            s = self.score(
                title=t.get("title", ""),
                description=t.get("description", ""),
                due_in_hours=t.get("due_in_hours"),
            )
            results.append({**t, "score": s})
        results.sort(key=lambda x: x["score"].priority, reverse=True)
        return results

    def _keyword_score(self, text: str, keywords: dict, base: float) -> float:
        score = base
        for kw, boost in keywords.items():
            if kw in text:
                score = max(score, boost)
        return score

    def _due_urgency(self, hours: float) -> float:
        if hours <= 0:
            return 1.0
        if hours <= 2:
            return 0.95
        if hours <= 8:
            return 0.85
        if hours <= 24:
            return 0.75
        if hours <= 72:
            return 0.55
        return 0.3

    def _quadrant(self, urgency: float, importance: float) -> str:
        u_high = urgency >= 0.6
        i_high = importance >= 0.6
        if u_high and i_high:
            return "do_now"
        if not u_high and i_high:
            return "schedule"
        if u_high and not i_high:
            return "delegate"
        return "eliminate"


prioritizer = Prioritizer()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_prioritizer.py -v
# Expected: 4 PASS
```

- [ ] **Step 5: Commit**

```bash
git add src/tasks/__init__.py src/tasks/prioritizer.py tests/test_prioritizer.py
git commit -m "feat: Eisenhower matrix task prioritization engine"
```

---

## Task 9: Voice Transcription + Formatting Utils

**Files:**
- Create: `src/utils/__init__.py` _(empty)_
- Create: `src/utils/transcription.py`
- Create: `src/utils/formatting.py`

- [ ] **Step 1: Implement `src/utils/transcription.py`**

```python
import os
from pathlib import Path
from ..config import settings

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
            download_root=settings.whisper_model_path,
        )
    return _model


def transcribe_audio(audio_path: str) -> str:
    model = _get_model()
    segments, _ = model.transcribe(audio_path, beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip()
```

- [ ] **Step 2: Implement `src/utils/formatting.py`**

```python
import re


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", text)


def format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "No pending tasks."
    lines = ["*Your prioritized tasks:*\n"]
    quad_emoji = {
        "do_now": "🔴",
        "schedule": "🟡",
        "delegate": "🔵",
        "eliminate": "⚪",
    }
    for i, t in enumerate(tasks, 1):
        emoji = quad_emoji.get(t.get("quadrant", ""), "⚪")
        due_str = f" _(due: {t['due_date']})_" if t.get("due_date") else ""
        lines.append(f"{i}\\. {emoji} {escape_md(t['title'])}{due_str}")
    return "\n".join(lines)


def format_email_summary(emails: list[dict]) -> str:
    if not emails:
        return "No unread emails."
    lines = ["*Unread emails:*\n"]
    for e in emails[:5]:
        subject = escape_md(e.get("subject", "No subject"))
        sender = escape_md(e.get("from", "Unknown"))
        lines.append(f"• *{subject}*\n  From: {sender}")
    if len(emails) > 5:
        lines.append(f"_…and {len(emails) - 5} more_")
    return "\n".join(lines)


def format_calendar_events(events: list[dict]) -> str:
    if not events:
        return "No upcoming events."
    lines = ["*Upcoming events:*\n"]
    for e in events[:8]:
        title = escape_md(e.get("summary", "No title"))
        start = escape_md(str(e.get("start", "")))
        lines.append(f"📅 *{title}*\n  {start}")
    return "\n".join(lines)


def truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n\n_[truncated]_"
```

- [ ] **Step 3: Commit**

```bash
git add src/utils/__init__.py src/utils/transcription.py src/utils/formatting.py
git commit -m "feat: voice transcription (faster-whisper) and formatting helpers"
```

---

## Task 10: Claude Tools Registry

**Files:**
- Create: `src/ai/__init__.py` _(empty)_
- Create: `src/ai/tools.py`

- [ ] **Step 1: Implement `src/ai/tools.py`**

All Google integrations are registered as Claude tools here. The dispatcher maps tool names to implementation functions.

```python
from typing import Any
from ..integrations.gmail import gmail
from ..integrations.gcalendar import gcalendar
from ..integrations.gdrive import gdrive
from ..integrations.gtasks import gtasks
from ..tasks.prioritizer import prioritizer

# ── Tool Schemas ────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "gmail_list_unread",
        "description": "List unread emails from Gmail. Returns subject, sender, date, snippet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 10, "description": "Max emails to return"}
            },
        },
    },
    {
        "name": "gmail_search",
        "description": "Search Gmail emails by query string (supports Gmail search operators like from:, subject:, after:).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_mark_read",
        "description": "Mark an email as read.",
        "input_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    {
        "name": "calendar_list_events",
        "description": "List upcoming Google Calendar events for the next N days.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7, "description": "Days ahead to fetch"}},
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a Google Calendar event. start/end are ISO 8601 datetime strings in UTC.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "ISO 8601 UTC datetime e.g. 2026-05-10T14:00:00Z"},
                "end": {"type": "string", "description": "ISO 8601 UTC datetime"},
                "description": {"type": "string", "default": ""},
                "location": {"type": "string", "default": ""},
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "calendar_search_events",
        "description": "Search for calendar events by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "days": {"type": "integer", "default": 30},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_search",
        "description": "Search Google Drive files by name or content. Supports Drive query syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Drive search query e.g. \"name contains 'report'\""},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_list_recent",
        "description": "List recently modified Drive files.",
        "input_schema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer", "default": 10}},
        },
    },
    {
        "name": "tasks_list",
        "description": "List tasks from Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "tasks_create",
        "description": "Create a new task in Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "notes": {"type": "string", "default": ""},
                "due": {"type": "string", "description": "RFC 3339 datetime e.g. 2026-05-10T00:00:00Z (optional)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "tasks_complete",
        "description": "Mark a Google Task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "prioritize_tasks",
        "description": "Score and rank a list of tasks by urgency and importance using the Eisenhower matrix.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "due_in_hours": {"type": "number"},
                        },
                        "required": ["title"],
                    },
                }
            },
            "required": ["tasks"],
        },
    },
]


# ── Dispatcher ───────────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> Any:
    """Execute a tool by name and return its result as a JSON-serializable object."""
    match tool_name:
        case "gmail_list_unread":
            return gmail.list_unread(tool_input.get("max_results", 10))
        case "gmail_search":
            return gmail.search(tool_input["query"], tool_input.get("max_results", 10))
        case "gmail_mark_read":
            gmail.mark_read(tool_input["message_id"])
            return {"status": "marked_read"}
        case "calendar_list_events":
            return gcalendar.list_events(tool_input.get("days", 7))
        case "calendar_create_event":
            return gcalendar.create_event(
                title=tool_input["title"],
                start=tool_input["start"],
                end=tool_input["end"],
                description=tool_input.get("description", ""),
                location=tool_input.get("location", ""),
            )
        case "calendar_search_events":
            return gcalendar.search_events(tool_input["query"], tool_input.get("days", 30))
        case "drive_search":
            return gdrive.search(tool_input["query"], tool_input.get("max_results", 10))
        case "drive_list_recent":
            return gdrive.list_recent(tool_input.get("max_results", 10))
        case "tasks_list":
            return gtasks.list_tasks(tool_input.get("max_results", 20))
        case "tasks_create":
            return gtasks.create_task(
                title=tool_input["title"],
                notes=tool_input.get("notes", ""),
                due=tool_input.get("due"),
            )
        case "tasks_complete":
            return gtasks.complete_task(tool_input["task_id"])
        case "prioritize_tasks":
            scored = prioritizer.score_list(tool_input["tasks"])
            return [
                {
                    **{k: v for k, v in t.items() if k != "score"},
                    "urgency": t["score"].urgency,
                    "importance": t["score"].importance,
                    "priority": t["score"].priority,
                    "quadrant": t["score"].quadrant,
                }
                for t in scored
            ]
        case _:
            return {"error": f"Unknown tool: {tool_name}"}
```

- [ ] **Step 2: Commit**

```bash
git add src/ai/__init__.py src/ai/tools.py
git commit -m "feat: Claude tool schemas and dispatcher for all Google integrations"
```

---

## Task 11: Claude AI Client

**Files:**
- Create: `src/ai/claude_client.py`
- Test: `tests/test_claude_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_claude_client.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

@pytest.mark.asyncio
async def test_chat_no_tools():
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(type="text", text="Hello! How can I help?")]

    with patch("src.ai.claude_client.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client

        from src.ai.claude_client import ClaudeClient
        client = ClaudeClient()
        result = await client.chat(
            telegram_id=123,
            user_message="Hello",
            conversation_history=[],
        )
        assert "Hello" in result or len(result) > 0

@pytest.mark.asyncio
async def test_chat_with_tool_use():
    text_response = MagicMock()
    text_response.stop_reason = "end_turn"
    text_response.content = [MagicMock(type="text", text="Here are your tasks.")]

    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_abc"
    tool_block.name = "tasks_list"
    tool_block.input = {"max_results": 5}
    tool_response.content = [tool_block]

    with patch("src.ai.claude_client.anthropic.Anthropic") as mock_cls, \
         patch("src.ai.claude_client.dispatch_tool") as mock_dispatch:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [tool_response, text_response]
        mock_cls.return_value = mock_client
        mock_dispatch.return_value = [{"id": "t1", "title": "Buy milk"}]

        from src.ai.claude_client import ClaudeClient
        client = ClaudeClient()
        result = await client.chat(123, "List my tasks", [])
        assert mock_dispatch.called
        assert len(result) > 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_claude_client.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/ai/claude_client.py`**

```python
import json
import logging
from typing import Optional
import anthropic

from ..config import settings
from .tools import TOOL_SCHEMAS, dispatch_tool
from ..memory.context_retriever import context_retriever

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a personal assistant with access to Gmail, Google Calendar, Google Drive, and Google Tasks.
You are helpful, concise, and proactive. You remember past conversations and user preferences.

When the user asks you to do something with their email, calendar, files, or tasks — use the available tools.
Always confirm actions before making changes unless the user has said otherwise.
Format responses for Telegram (use markdown, keep messages under 4000 chars).
Today's date: {date}

Relevant context from past conversations:
{context}
"""


class ClaudeClient:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def chat(
        self,
        telegram_id: int,
        user_message: str,
        conversation_history: list[dict],
        date_str: str = "",
    ) -> str:
        from datetime import date
        if not date_str:
            date_str = date.today().isoformat()

        # Fetch semantically relevant past context
        relevant_ctx = await context_retriever.get_relevant_context(
            telegram_id, user_message, n=5
        )

        system = SYSTEM_PROMPT.format(date=date_str, context=relevant_ctx or "None")

        # Build message list for Claude
        messages = self._build_messages(conversation_history, user_message)

        response_text = await self._run_tool_loop(messages, system)

        # Store this exchange in vector memory
        await context_retriever.store_message(
            telegram_id, "user", user_message, f"{telegram_id}_{date_str}_u_{len(messages)}"
        )
        await context_retriever.store_message(
            telegram_id, "assistant", response_text, f"{telegram_id}_{date_str}_a_{len(messages)}"
        )
        return response_text

    def _build_messages(self, history: list[dict], user_message: str) -> list[dict]:
        messages = []
        for m in history:
            role = m["role"]
            if role not in ("user", "assistant"):
                continue
            tool_calls = m.get("tool_calls")
            if tool_calls and role == "assistant":
                messages.append({"role": "assistant", "content": tool_calls})
            else:
                messages.append({"role": role, "content": m["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _run_tool_loop(self, messages: list[dict], system: str) -> str:
        for _ in range(10):  # max 10 tool-use rounds
            response = self._client.messages.create(
                model=settings.claude_model,
                max_tokens=4096,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info("Tool call: %s %s", block.name, block.input)
                        try:
                            result = dispatch_tool(block.name, block.input)
                        except Exception as exc:
                            logger.error("Tool %s failed: %s", block.name, exc)
                            result = {"error": str(exc)}
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            }
                        )
                # Append assistant tool-use turn and tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                return self._extract_text(response)

        return "I ran into an issue completing that. Please try again."

    def _extract_text(self, response) -> str:
        parts = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(parts).strip() or "Done."


claude_client = ClaudeClient()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_claude_client.py -v
# Expected: 2 PASS
```

- [ ] **Step 5: Commit**

```bash
git add src/ai/claude_client.py tests/test_claude_client.py
git commit -m "feat: Claude AI client with tool-use loop and vector memory context"
```

---

## Task 12: Telegram Bot Handlers

**Files:**
- Create: `src/bot/__init__.py` _(empty)_
- Create: `src/bot/handlers/__init__.py` _(empty)_
- Create: `src/bot/handlers/commands.py`
- Create: `src/bot/handlers/messages.py`
- Create: `src/bot/handlers/voice.py`
- Test: `tests/test_handlers.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_handlers.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.message.reply_text = AsyncMock()
    update.message.text = "List my emails"
    return update

@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()
    return ctx

@pytest.mark.asyncio
async def test_message_handler_allowed_user(mock_update, mock_context):
    with patch("src.bot.handlers.messages.settings") as mock_s, \
         patch("src.bot.handlers.messages.db") as mock_db, \
         patch("src.bot.handlers.messages.claude_client") as mock_claude:
        mock_s.telegram_allowed_users = [12345]
        mock_db.upsert_user = AsyncMock()
        mock_db.save_message = AsyncMock()
        mock_db.get_recent_messages = AsyncMock(return_value=[])
        mock_claude.chat = AsyncMock(return_value="Here are your emails.")

        from src.bot.handlers.messages import handle_message
        await handle_message(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()

@pytest.mark.asyncio
async def test_message_handler_blocked_user(mock_update, mock_context):
    with patch("src.bot.handlers.messages.settings") as mock_s:
        mock_s.telegram_allowed_users = [99999]  # 12345 not in list
        from src.bot.handlers.messages import handle_message
        await handle_message(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, you're not authorized to use this bot."
        )
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_handlers.py -v
# Expected: ImportError
```

- [ ] **Step 3: Implement `src/bot/handlers/commands.py`**

```python
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.formatting import format_task_list, format_calendar_events, truncate

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    return not settings.telegram_allowed_users or user_id in settings.telegram_allowed_users


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm your personal assistant.\n\n"
        "I can help you with:\n"
        "• 📧 Reading and managing emails\n"
        "• 📅 Calendar and reminders\n"
        "• 📂 Finding Drive files\n"
        "• ✅ Managing tasks\n\n"
        "Just send me a message and I'll get to work. "
        "Use /briefing for your daily summary or /tasks to see your task list."
    )


async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=(
            "Give me my daily briefing: summarize unread emails, "
            "list today's calendar events, and show my top 5 tasks by priority."
        ),
        conversation_history=[],
    )
    await update.message.reply_text(truncate(response), parse_mode="Markdown")


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    tasks = await db.get_pending_tasks(user.id)
    msg = format_task_list(tasks)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/briefing — Get your daily briefing\n"
        "/tasks — Show your task list\n"
        "/help — This help message\n\n"
        "Or just send me any message or a voice note!",
        parse_mode="Markdown",
    )
```

- [ ] **Step 4: Implement `src/bot/handlers/messages.py`**

```python
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.formatting import truncate

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    return not settings.telegram_allowed_users or user_id in settings.telegram_allowed_users


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    text = update.message.text or ""
    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)

    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=text,
        conversation_history=history,
    )

    await db.save_message(user.id, "user", text)
    await db.save_message(user.id, "assistant", response)

    await update.message.reply_text(truncate(response), parse_mode="Markdown")
```

- [ ] **Step 5: Implement `src/bot/handlers/voice.py`**

```python
import logging
import os
import tempfile
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.transcription import transcribe_audio
from ...utils.formatting import truncate

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    return not settings.telegram_allowed_users or user_id in settings.telegram_allowed_users


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await db.upsert_user(user.id, user.username or "", user.first_name or "")

    # Download voice file from Telegram
    voice_file = await update.message.voice.get_file()
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await voice_file.download_to_drive(tmp_path)
        transcript = transcribe_audio(tmp_path)
    finally:
        os.unlink(tmp_path)

    if not transcript:
        await update.message.reply_text("Sorry, I couldn't transcribe that voice message.")
        return

    # Echo transcript so user knows what was heard
    await update.message.reply_text(f"_Heard: {transcript}_", parse_mode="Markdown")

    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=transcript,
        conversation_history=history,
    )

    await db.save_message(user.id, "user", transcript)
    await db.save_message(user.id, "assistant", response)
    await update.message.reply_text(truncate(response), parse_mode="Markdown")
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_handlers.py -v
# Expected: 2 PASS
```

- [ ] **Step 7: Commit**

```bash
git add src/bot/__init__.py src/bot/handlers/__init__.py \
        src/bot/handlers/commands.py src/bot/handlers/messages.py \
        src/bot/handlers/voice.py tests/test_handlers.py
git commit -m "feat: Telegram handlers for commands, messages, and voice notes"
```

---

## Task 13: Telegram Bot Lifecycle

**Files:**
- Create: `src/bot/telegram_bot.py`

- [ ] **Step 1: Implement `src/bot/telegram_bot.py`**

```python
import logging
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from ..config import settings
from .handlers.commands import start_command, briefing_command, tasks_command, help_command
from .handlers.messages import handle_message
from .handlers.voice import handle_voice

logger = logging.getLogger(__name__)


def build_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("briefing", briefing_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
```

- [ ] **Step 2: Commit**

```bash
git add src/bot/telegram_bot.py
git commit -m "feat: Telegram application builder with all handler registrations"
```

---

## Task 14: Conversation History Manager

**Files:**
- Create: `src/memory/conversation.py`

- [ ] **Step 1: Implement `src/memory/conversation.py`**

This module provides a clean interface for building the Claude message array from the database records.

```python
from .database import db
from ..config import settings


class ConversationManager:
    async def get_history(self, telegram_id: int) -> list[dict]:
        """Return last N messages formatted for the Claude messages API."""
        raw = await db.get_recent_messages(telegram_id, limit=settings.conversation_window)
        messages = []
        for m in raw:
            if m["role"] == "user":
                messages.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                if m.get("tool_calls"):
                    messages.append({"role": "assistant", "content": m["tool_calls"]})
                else:
                    messages.append({"role": "assistant", "content": m["content"]})
        return messages

    async def add_exchange(self, telegram_id: int, user_text: str, assistant_text: str):
        await db.save_message(telegram_id, "user", user_text)
        await db.save_message(telegram_id, "assistant", assistant_text)


conversation_manager = ConversationManager()
```

- [ ] **Step 2: Commit**

```bash
git add src/memory/conversation.py
git commit -m "feat: conversation history manager"
```

---

## Task 15: Scheduler — Daily Briefing + Proactive Reminders

**Files:**
- Create: `src/scheduler/__init__.py` _(empty)_
- Create: `src/scheduler/briefing.py`
- Create: `src/scheduler/reminders.py`

- [ ] **Step 1: Implement `src/scheduler/briefing.py`**

```python
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from ..config import settings
from ..memory.database import db
from ..ai.claude_client import claude_client
from ..utils.formatting import truncate

logger = logging.getLogger(__name__)


async def _send_briefing(bot, telegram_id: int):
    logger.info("Sending daily briefing to %s", telegram_id)
    response = await claude_client.chat(
        telegram_id=telegram_id,
        user_message=(
            "Good morning! Please give me my daily briefing: "
            "1) Summarize any important unread emails from the last 24h. "
            "2) List today's calendar events. "
            "3) Show my top 5 priority tasks. "
            "Keep it concise."
        ),
        conversation_history=[],
        date_str=datetime.now().date().isoformat(),
    )
    await db.save_briefing(telegram_id, response)
    await bot.send_message(chat_id=telegram_id, text=truncate(response), parse_mode="Markdown")


def schedule_briefings(scheduler: AsyncIOScheduler, bot):
    hour, minute = settings.briefing_time.split(":")
    tz = pytz.timezone(settings.timezone)
    trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)

    async def job():
        users_with_briefing = await db.get_recent_messages.__self__._db.execute_fetchall(
            "SELECT DISTINCT telegram_id FROM users"
        ) if False else None
        # Fetch all registered users and send each a briefing
        async with db._db.execute("SELECT telegram_id FROM users") as cursor:
            users = await cursor.fetchall()
        for row in users:
            try:
                await _send_briefing(bot, row[0])
            except Exception as exc:
                logger.error("Briefing failed for %s: %s", row[0], exc)

    scheduler.add_job(job, trigger, id="daily_briefing", replace_existing=True)
    logger.info("Daily briefing scheduled at %s %s", settings.briefing_time, settings.timezone)
```

- [ ] **Step 2: Implement `src/scheduler/reminders.py`**

```python
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..memory.database import db
from ..integrations.gcalendar import gcalendar
from ..integrations.gtasks import gtasks

logger = logging.getLogger(__name__)

REMINDER_MINUTES_BEFORE = [60, 15]


async def _check_and_send_reminders(bot):
    async with db._db.execute("SELECT telegram_id FROM users") as cursor:
        users = await cursor.fetchall()

    now = datetime.now(timezone.utc)
    for row in users:
        tid = row[0]
        try:
            events = gcalendar.list_events(days=1)
            for event in events:
                start_str = event.get("start", "")
                if not start_str:
                    continue
                try:
                    from dateutil.parser import parse
                    start_dt = parse(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                minutes_until = (start_dt - now).total_seconds() / 60
                for threshold in REMINDER_MINUTES_BEFORE:
                    if abs(minutes_until - threshold) < 5:  # within 5-min window
                        msg = (
                            f"⏰ *Reminder:* {event['summary']} starts in "
                            f"{threshold} minutes."
                        )
                        await bot.send_message(chat_id=tid, text=msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Reminder check failed for %s: %s", tid, exc)


def schedule_reminders(scheduler: AsyncIOScheduler, bot):
    async def job():
        await _check_and_send_reminders(bot)

    scheduler.add_job(
        job,
        IntervalTrigger(minutes=5),
        id="reminder_check",
        replace_existing=True,
    )
    logger.info("Reminder checker scheduled every 5 minutes")
```

- [ ] **Step 3: Commit**

```bash
git add src/scheduler/__init__.py src/scheduler/briefing.py src/scheduler/reminders.py
git commit -m "feat: APScheduler jobs for daily briefing and proactive reminders"
```

---

## Task 16: Main Entry Point

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Implement `src/main.py`**

```python
import asyncio
import logging
import signal
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .memory.database import db
from .memory.vector_store import vector_store
from .bot.telegram_bot import build_application
from .scheduler.briefing import schedule_briefings
from .scheduler.reminders import schedule_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    logger.info("Starting personal assistant bot...")

    # Initialize persistent storage
    await db.connect()
    vector_store.init()
    logger.info("Database and vector store initialized")

    # Build Telegram application
    app = build_application()

    # Set up scheduler
    scheduler = AsyncIOScheduler()
    schedule_briefings(scheduler, app.bot)
    schedule_reminders(scheduler, app.bot)
    scheduler.start()
    logger.info("Scheduler started")

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Start polling
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot is running. Waiting for messages...")

    await stop_event.wait()

    logger.info("Shutting down...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    scheduler.shutdown()
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add src/main.py
git commit -m "feat: main entry point wiring bot, scheduler, DB, and vector store"
```

---

## Task 17: conftest + Integration Tests

**Files:**
- Create: `tests/__init__.py` _(empty)_
- Create: `tests/conftest.py`

- [ ] **Step 1: Implement `tests/conftest.py`**

```python
import pytest
import tempfile
import os
from unittest.mock import patch, MagicMock

@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Patch settings for all tests to use safe defaults."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "12345")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/tmp/fake_creds.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "/tmp/fake_token.json")
    monkeypatch.setenv("BRIEFING_TIME", "08:00")
    monkeypatch.setenv("TIMEZONE", "UTC")


@pytest.fixture
def tmp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def tmp_chroma_path():
    with tempfile.TemporaryDirectory() as d:
        yield d
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v --tb=short
# Expected: All tests PASS
```

- [ ] **Step 3: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: conftest with shared fixtures and settings patches"
```

---

## Task 18: Final Wiring Verification

- [ ] **Step 1: Verify `src/__init__.py` and all `__init__.py` files exist**

```bash
# Each package needs an __init__.py:
touch src/__init__.py
touch src/ai/__init__.py
touch src/bot/__init__.py
touch src/bot/handlers/__init__.py
touch src/integrations/__init__.py
touch src/memory/__init__.py
touch src/scheduler/__init__.py
touch src/tasks/__init__.py
touch src/utils/__init__.py
touch tests/__init__.py
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
# Expected: All tests PASS
```

- [ ] **Step 3: Verify Docker builds**

```bash
docker-compose build
# Expected: Build completes without errors (whisper model downloads to layer cache)
```

- [ ] **Step 4: Verify imports wire correctly (no circular imports)**

```bash
python -c "from src.main import main; print('Import OK')"
# Expected: Import OK (run from project root with TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY set)
```

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "chore: verify all __init__.py files and confirm clean import tree"
```

---

## Self-Review Against Spec

| Requirement | Task(s) |
|---|---|
| Read and summarize emails | Task 6 (Gmail), Task 10 (tool), Task 11 (Claude loop) |
| Manage calendar and reminders | Task 7 (Calendar), Task 15 (reminders) |
| Search and organize Drive files | Task 7 (Drive), Task 10 (tool) |
| Create and prioritize tasks | Task 5 (Tasks), Task 8 (prioritizer) |
| Daily briefings | Task 15 (briefing job) |
| Voice notes → tasks | Task 9 (transcription), Task 12 (voice handler) |
| Email → action | Task 11 (Claude client reads emails via tools) |
| Persistent memory (SQLite) | Task 3 |
| Vector search memory (ChromaDB) | Task 4 |
| Daily morning briefing | Task 15 |
| Proactive reminders | Task 15 |
| Prioritization engine | Task 8 |
| Conversation history per user | Task 3, 14 |
| Python + claude-sonnet-4-6 | Tasks 2, 11 |
| Dockerfile + docker-compose.yml | Task 1 |
| .env template | Task 1 |
| Google Tasks credentials as volume | Task 1 (docker-compose volumes) |
| Production-grade, not prototype | Throughout: async, error handling, logging, graceful shutdown |
