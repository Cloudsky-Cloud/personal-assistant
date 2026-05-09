import asyncio
import json
import logging
import signal
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .memory.database import db
from .memory.vector_store import vector_store
from .bot.telegram_bot import build_application
from .scheduler.briefing import schedule_briefings
from .scheduler.reminders import schedule_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# ChromaDB's PostHog telemetry client has a broken API — suppress its errors.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


def _check_google_token_scopes() -> None:
    """Log the scopes on the saved OAuth token so misconfiguration is visible at startup."""
    token_path = Path(settings.google_token_file)
    if not token_path.exists():
        logger.warning("Google token not found at %s — run setup_auth.py", token_path)
        return
    try:
        data = json.loads(token_path.read_text())
        scopes = data.get("scopes") or []
        logger.info("Google token scopes: %s", scopes)
        contacts_scope = "https://www.googleapis.com/auth/contacts"
        if contacts_scope not in scopes:
            logger.error(
                "Google token is MISSING scope %s — "
                "delete %s and re-run: docker-compose run --rm bot python setup_auth.py",
                contacts_scope, token_path,
            )
    except Exception as exc:
        logger.warning("Could not read Google token scopes: %s", exc)


async def main():
    logger.info("Starting personal assistant bot...")
    _check_google_token_scopes()

    # Persistent storage
    await db.connect()
    vector_store.init()
    logger.info("Database and vector store ready")

    # Telegram application
    app = build_application()

    # Background scheduler
    scheduler = AsyncIOScheduler()
    schedule_briefings(scheduler, app.bot)
    schedule_reminders(scheduler, app.bot)
    scheduler.start()
    logger.info("Scheduler started")

    # Graceful shutdown on SIGINT / SIGTERM
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot is polling for messages...")

    await stop_event.wait()

    logger.info("Shutdown signal received, stopping...")
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    scheduler.shutdown(wait=False)
    await db.close()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
