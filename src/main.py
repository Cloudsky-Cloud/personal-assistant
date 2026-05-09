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
