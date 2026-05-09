from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


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
