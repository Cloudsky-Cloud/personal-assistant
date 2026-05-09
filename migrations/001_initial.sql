CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username    TEXT,
    first_name  TEXT,
    preferences TEXT DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    role         TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'tool', 'tool_result')),
    content      TEXT NOT NULL,
    tool_calls   TEXT,
    tool_call_id TEXT,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id      INTEGER NOT NULL,
    title            TEXT NOT NULL,
    description      TEXT DEFAULT '',
    urgency_score    REAL DEFAULT 0.5,
    importance_score REAL DEFAULT 0.5,
    priority_score   REAL DEFAULT 0.5,
    status           TEXT DEFAULT 'pending',
    due_date         TEXT,
    gtasks_id        TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
);

CREATE TABLE IF NOT EXISTS briefing_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    sent_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_tid    ON conversations(telegram_id);
CREATE INDEX IF NOT EXISTS idx_conv_ts     ON conversations(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_tid   ON tasks(telegram_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
