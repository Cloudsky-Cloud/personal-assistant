import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dateutil.parser import parse as parse_dt

from ..memory.database import db
from ..integrations.gcalendar import gcalendar

logger = logging.getLogger(__name__)

# Send reminders at these many minutes before an event
_REMINDER_THRESHOLDS = [60, 15]
# How wide the match window is (±minutes)
_WINDOW_MINUTES = 4


async def _check_reminders(bot):
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return

    now = datetime.now(timezone.utc)

    for uid in user_ids:
        try:
            events = gcalendar.list_events(days=1)
        except Exception as exc:
            logger.warning("Calendar fetch failed for user %s: %s", uid, exc)
            continue

        for event in events:
            start_str = event.get("start", "")
            if not start_str:
                continue
            try:
                start_dt = parse_dt(start_str)
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            minutes_until = (start_dt - now).total_seconds() / 60

            for threshold in _REMINDER_THRESHOLDS:
                if abs(minutes_until - threshold) <= _WINDOW_MINUTES:
                    title = event.get("summary", "Event")
                    msg = (
                        f"⏰ *Reminder:* _{title}_ starts in "
                        f"{threshold} minute{'s' if threshold != 1 else ''}."
                    )
                    try:
                        await bot.send_message(
                            chat_id=uid, text=msg, parse_mode="Markdown"
                        )
                    except Exception as exc:
                        logger.error("Reminder send failed for user %s: %s", uid, exc)


def schedule_reminders(scheduler: AsyncIOScheduler, bot):
    async def job():
        await _check_reminders(bot)

    scheduler.add_job(
        job,
        IntervalTrigger(minutes=5),
        id="reminder_check",
        replace_existing=True,
    )
    logger.info("Reminder checker scheduled every 5 minutes")
