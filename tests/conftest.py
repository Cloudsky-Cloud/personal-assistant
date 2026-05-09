"""
Set test env vars at import time so src.config.Settings() succeeds
during pytest collection, before any fixture or monkeypatch runs.
"""
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_123")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key")
os.environ.setdefault("TELEGRAM_ALLOWED_USERS", "12345,99999")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "/tmp/fake_creds.json")
os.environ.setdefault("GOOGLE_TOKEN_FILE", "/tmp/fake_token.json")
os.environ.setdefault("DB_PATH", "/tmp/test_assistant.db")
os.environ.setdefault("CHROMA_PATH", "/tmp/test_chroma")
os.environ.setdefault("WHISPER_MODEL_PATH", "/tmp/test_whisper")
os.environ.setdefault("BRIEFING_TIME", "08:00")
os.environ.setdefault("TIMEZONE", "UTC")

import pytest


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Patch settings attributes per-test for isolation."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "12345,99999")
