from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Telegram
    telegram_bot_token: str
    # Comma-separated user IDs: "111,222,333" — empty means no restriction
    telegram_allowed_users: str = ""

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

    # Weather (wttr.in — no API key required)
    weather_city: str = ""
    weather_country: str = ""

    # Scheduler
    briefing_time: str = "08:00"
    timezone: str = "UTC"

    # Tuning
    whisper_model: str = "base"
    conversation_window: int = 30

    def allowed_user_ids(self) -> list[int]:
        """Parse TELEGRAM_ALLOWED_USERS into a list of ints. Empty = no restriction."""
        raw = self.telegram_allowed_users.strip()
        if not raw:
            return []
        return [int(x.strip()) for x in raw.split(",") if x.strip()]


settings = Settings()
