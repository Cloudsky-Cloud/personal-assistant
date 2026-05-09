import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from ..memory.database import db
from ..ai.claude_client import claude_client
from ..utils.formatting import truncate

logger = logging.getLogger(__name__)


async def _send_briefing(bot, telegram_id: int):
    logger.info("Sending daily briefing to user %s", telegram_id)
    try:
        response = await claude_client.chat(
            telegram_id=telegram_id,
            user_message=(
                "Good morning! Please give me my daily briefing:\n"
                "1) Summarize any important unread emails from the last 24 hours.\n"
                "2) List today's calendar events with times.\n"
                "3) Show my top 5 priority tasks.\n"
                "Keep it concise and actionable."
            ),
            conversation_history=[],
            date_str=datetime.now().date().isoformat(),
        )
        await db.save_briefing(telegram_id, response)
        await bot.send_message(
            chat_id=telegram_id,
            text=truncate(response),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("Briefing failed for user %s: %s", telegram_id, exc)


def schedule_briefings(scheduler: AsyncIOScheduler, bot):
    hour, minute = settings.briefing_time.split(":")
    tz = pytz.timezone(settings.timezone)

    async def job():
        user_ids = await db.get_all_user_ids()
        for uid in user_ids:
            await _send_briefing(bot, uid)

    scheduler.add_job(
        job,
        CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
        id="daily_briefing",
        replace_existing=True,
    )
    logger.info(
        "Daily briefing scheduled at %s %s", settings.briefing_time, settings.timezone
    )
