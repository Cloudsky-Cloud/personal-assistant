"""Dream cycle: nightly consolidation of the day's conversations into GBrain.

Runs at 2 AM in the configured timezone. Reads all user+assistant messages
from the past 24 hours, asks Claude to extract people, decisions, and key
facts, then stores everything in GBrain as hot-memory facts and a daily log page.
"""
import logging
from datetime import datetime, timedelta, timezone

import anthropic
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from ..memory.database import db
from ..integrations.gbrain import gbrain

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """\
Below is a transcript of all conversations from today. Extract the following as plain text:

1. **People mentioned** — name and anything learned about them (role, contact info, relationship)
2. **Decisions made** — what was decided and why
3. **Tasks created or discussed** — title and context
4. **Key facts to remember** — anything the user explicitly wanted stored, or that seems important
5. **Emails sent** — to whom and subject
6. **Calendar events created** — title, date, time

Be concise. Skip pleasantries and filler. Format as markdown.

TRANSCRIPT:
{transcript}
"""


async def _run_dream_cycle():
    if not gbrain.enabled():
        logger.info("Dream cycle skipped — GBrain not configured")
        return

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    messages = await db.get_messages_since(since)

    if not messages:
        logger.info("Dream cycle: no conversations in the past 24h")
        return

    logger.info("Dream cycle: processing %d messages", len(messages))

    # Build readable transcript (cap at ~12 000 chars to stay inside context)
    lines: list[str] = []
    for m in messages:
        role = m["role"].capitalize()
        content = (m["content"] or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    transcript = "\n\n".join(lines)[:12_000]

    # Ask Claude to extract structured knowledge
    try:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": _EXTRACTION_PROMPT.format(transcript=transcript),
            }],
        )
        summary = resp.content[0].text.strip()
    except Exception as exc:
        logger.error("Dream cycle: Claude extraction failed: %s", exc)
        summary = transcript[:3000]  # fall back to raw transcript

    today_str = datetime.now().strftime("%Y-%m-%d")
    session_id = f"dream-{today_str}"

    # Write structured facts to hot memory
    await gbrain.extract_facts(summary, session_id=session_id)

    # Write a dated daily log page
    page_content = (
        f"---\n"
        f"date: {today_str}\n"
        f"tags: [daily-log]\n"
        f"---\n\n"
        f"# Daily Log — {today_str}\n\n"
        f"{summary}"
    )
    await gbrain.put_page(f"logs/daily/{today_str}", page_content)

    logger.info("Dream cycle complete for %s", today_str)


def schedule_dream_cycle(scheduler: AsyncIOScheduler):
    tz = pytz.timezone(settings.timezone)
    scheduler.add_job(
        _run_dream_cycle,
        CronTrigger(hour=2, minute=0, timezone=tz),
        id="dream_cycle",
        replace_existing=True,
    )
    logger.info("Dream cycle scheduled at 02:00 %s", settings.timezone)
