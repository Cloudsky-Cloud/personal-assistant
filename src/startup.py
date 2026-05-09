import json
import logging
import sys
from pathlib import Path

from .config import settings
from .integrations.google_scopes import SCOPES

logger = logging.getLogger(__name__)


def _check_env_vars(errors: list[str]) -> None:
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your_"):
        errors.append("TELEGRAM_BOT_TOKEN is not configured")
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("your_"):
        errors.append("ANTHROPIC_API_KEY is not configured")


def _check_google_credentials(errors: list[str]) -> bool:
    creds_path = Path(settings.google_credentials_file)
    if not creds_path.exists():
        errors.append(
            f"Google credentials file not found: {creds_path}. "
            "Download OAuth2 credentials (Desktop app type) from Google Cloud Console "
            "and save as credentials/google_credentials.json"
        )
        return False
    return True


def _check_google_token(errors: list[str]) -> bool:
    token_path = Path(settings.google_token_file)
    if not token_path.exists():
        errors.append(
            f"Google token not found at {token_path}. "
            "Run: docker-compose run --rm bot python setup_auth.py"
        )
        return False

    try:
        data = json.loads(token_path.read_text())
        token_scopes = set(data.get("scopes") or [])
        missing = [s for s in SCOPES if s not in token_scopes]
        if missing:
            errors.append(
                f"Google token is missing required scopes: {missing}. "
                f"Delete {token_path} and re-run: "
                "docker-compose run --rm bot python setup_auth.py"
            )
            return False
    except Exception as exc:
        errors.append(f"Could not read Google token at {token_path}: {exc}")
        return False

    return True


def run_startup_checks() -> None:
    """Validate critical config. Calls sys.exit(1) if env vars or Google token are missing/invalid."""
    logger.info("Running startup checks...")
    errors: list[str] = []

    _check_env_vars(errors)
    _check_google_credentials(errors)
    _check_google_token(errors)

    if errors:
        logger.critical("=" * 60)
        logger.critical("BOT STARTUP FAILED — %d check(s) failed:", len(errors))
        for i, err in enumerate(errors, 1):
            logger.critical("  [%d] %s", i, err)
        logger.critical("=" * 60)
        sys.exit(1)

    logger.info("Startup checks passed.")
