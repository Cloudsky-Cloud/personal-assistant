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

# Python 3.14 changed unittest.mock.patch to resolve dotted target paths via
# pkgutil.resolve_name, which uses attribute access (getattr) rather than
# importlib.import_module. Submodules only become attributes of their parent
# package after they have been imported. Pre-import every module that tests
# reference in patch() so the resolver can find them.
import src.integrations.google_scopes      # noqa: F401
import src.integrations.google_auth        # noqa: F401
import src.integrations.gmail              # noqa: F401
import src.integrations.weather            # noqa: F401
import src.integrations.gcalendar          # noqa: F401
import src.integrations.gdrive             # noqa: F401
import src.integrations.gtasks             # noqa: F401
import src.integrations.gcontacts          # noqa: F401
import src.integrations.elevenlabs         # noqa: F401
import src.integrations.websearch          # noqa: F401
import src.memory.database                 # noqa: F401
import src.memory.contacts                 # noqa: F401
import src.memory.projects                 # noqa: F401
import src.memory.vector_store             # noqa: F401
import src.memory.context_retriever        # noqa: F401
import src.tasks.prioritizer               # noqa: F401
import src.ai.tools                        # noqa: F401
import src.ai.claude_client                # noqa: F401
import src.bot.handlers.messages           # noqa: F401
import src.bot.handlers.commands           # noqa: F401
import src.startup                         # noqa: F401


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Patch settings attributes per-test for isolation."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "12345,99999")
