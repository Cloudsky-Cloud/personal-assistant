CREATE TABLE IF NOT EXISTS energy_scores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL UNIQUE,
    score          INTEGER NOT NULL,
    level          TEXT NOT NULL,
    sleep_hours    REAL,
    sleep_minutes  INTEGER,
    heart_rate_bpm INTEGER,
    steps          INTEGER,
    active_minutes INTEGER,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_energy_scores_date ON energy_scores(date);
