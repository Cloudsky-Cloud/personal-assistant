import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .memory.database import db
from .memory.vector_store import vector_store
from .bot.telegram_bot import build_application
from .scheduler.briefing import schedule_briefings
from .scheduler.reminders import schedule_reminders
from .startup import run_startup_checks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# ChromaDB's PostHog telemetry client has a broken API — suppress its errors.
logging.getLogger("chromadb.telemetry").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

_API_ENABLE_LINKS = {
    "Gmail":             "https://console.cloud.google.com/apis/library/gmail.googleapis.com",
    "Calendar":          "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com",
    "Drive":             "https://console.cloud.google.com/apis/library/drive.googleapis.com",
    "Tasks":             "https://console.cloud.google.com/apis/library/tasks.googleapis.com",
    "People (Contacts)": "https://console.cloud.google.com/apis/library/people.googleapis.com",
    "Cloud TTS":         "https://console.cloud.google.com/apis/library/texttospeech.googleapis.com",
}

_API_PROBES = [
    ("Gmail", "gmail", "v1",
     lambda svc: svc.users().getProfile(userId="me").execute()),
    ("Calendar", "calendar", "v3",
     lambda svc: svc.calendarList().list(maxResults=1).execute()),
    ("Drive", "drive", "v3",
     lambda svc: svc.files().list(pageSize=1, fields="files(id)").execute()),
    ("Tasks", "tasks", "v1",
     lambda svc: svc.tasklists().list(maxResults=1).execute()),
    ("People (Contacts)", "people", "v1",
     lambda svc: svc.people().get(resourceName="people/me", personFields="names").execute()),
]


def _check_google_apis() -> None:
    """Probe each Google API at startup. Logs WARNING for disabled APIs — never crashes the bot."""
    try:
        from .integrations.google_auth import build_google_service
    except Exception as exc:
        logger.warning("Google API health check skipped — could not load credentials: %s", exc)
        return

    for name, api_name, api_version, probe in _API_PROBES:
        try:
            svc = build_google_service(api_name, api_version)
            probe(svc)
            logger.info("Google %s API: OK", name)
        except Exception as exc:
            msg = str(exc)
            if any(kw in msg for kw in ("has not been used", "disabled", "ACCESS_DISABLED")):
                logger.warning(
                    "Google %s API is not enabled — enable it at: %s",
                    name,
                    _API_ENABLE_LINKS.get(name, "https://console.cloud.google.com/apis"),
                )
            else:
                logger.warning("Google %s API health check failed: %s", name, exc)

    # Cloud TTS uses its own client (not Discovery-based)
    try:
        from .integrations.gtts import probe as _tts_probe
        _tts_probe()
        logger.info("Google Cloud TTS API: OK")
    except Exception as exc:
        msg = str(exc)
        if any(kw in msg for kw in ("has not been used", "disabled", "ACCESS_DISABLED")):
            logger.warning(
                "Google Cloud TTS API is not enabled — enable it at: %s",
                _API_ENABLE_LINKS["Cloud TTS"],
            )
        else:
            logger.warning("Google Cloud TTS API health check failed: %s", exc)


async def main():
    logger.info("Starting personal assistant bot...")
    run_startup_checks()
    _check_google_apis()

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
