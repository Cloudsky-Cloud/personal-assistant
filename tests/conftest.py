import pytest
import os


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Inject safe env defaults for all tests."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "12345")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/tmp/fake_creds.json")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", "/tmp/fake_token.json")
    monkeypatch.setenv("DB_PATH", "/tmp/test_assistant.db")
    monkeypatch.setenv("CHROMA_PATH", "/tmp/test_chroma")
    monkeypatch.setenv("WHISPER_MODEL_PATH", "/tmp/test_whisper")
    monkeypatch.setenv("BRIEFING_TIME", "08:00")
    monkeypatch.setenv("TIMEZONE", "UTC")
    # Force settings to reload with new env
    import importlib
    import src.config
    importlib.reload(src.config)
