import logging
from datetime import date, datetime, timezone

import anthropic
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dateutil.parser import parse as parse_dt

from ..config import settings
from ..memory.database import db
from ..memory.projects import projects_db
from ..integrations.gmail import gmail
from ..integrations.gcalendar import gcalendar
from ..integrations.gtasks import gtasks
from ..integrations.weather import get_weather

logger = logging.getLogger(__name__)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _clean_sender(from_str: str) -> str:
    """Extract display name from 'Name <email>' or return address as-is."""
    if "<" in from_str:
        return from_str.split("<")[0].strip().strip("\"'")
    return from_str.strip()


def _weather_emoji(condition: str) -> str:
    c = condition.lower()
    if "sunny" in c or "clear" in c:
        return "☀️"
    if "partly" in c or "overcast" in c:
        return "⛅"
    if "thunder" in c or "storm" in c:
        return "⛈"
    if "rain" in c or "drizzle" in c or "shower" in c:
        return "🌧"
    if "snow" in c or "blizzard" in c:
        return "❄️"
    if "fog" in c or "mist" in c or "haze" in c:
        return "🌫"
    if "cloud" in c:
        return "☁️"
    return "🌤"


def _section_weather(city: str, country: str) -> str:
    w = get_weather(city, country)
    if not w:
        return ""
    loc = f"{city}, {country}" if country else city
    emoji = _weather_emoji(w["condition"])
    return (
        f"{emoji} *Weather — {loc}*\n"
        f"{w['condition']} · {w['temp_c']}°C (feels like {w['feels_like_c']}°C)\n"
        f"💧 {w['humidity']}% humidity · 💨 {w['wind_kmph']} km/h\n"
        f"🌡 High {w['max_c']}°C · Low {w['min_c']}°C"
    )


def _section_emails(emails: list[dict]) -> str:
    if not emails:
        return "📬 *Unread Emails*\nInbox is clear! 🎉"
    lines = [f"📬 *Unread Emails ({len(emails)})*"]
    for e in emails[:5]:
        subject = (e.get("subject") or "No subject")[:60].strip()
        sender = _clean_sender(e.get("from") or "Unknown")[:40]
        snippet = (e.get("snippet") or "").strip()[:100]
        lines.append(f"• *{subject}*")
        lines.append(f"  From: {sender}")
        if snippet:
            lines.append(f"  _{snippet}_")
    return "\n".join(lines)


def _section_calendar(events: list[dict], tz) -> str:
    today = datetime.now(tz).date()
    today_events: list[tuple[datetime, dict]] = []

    for e in events:
        start_str = e.get("start", "")
        if not start_str:
            continue
        try:
            dt = parse_dt(start_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_local = dt.astimezone(tz)
            if dt_local.date() == today:
                today_events.append((dt_local, e))
        except Exception:
            # All-day event stored as plain date string
            try:
                if date.fromisoformat(start_str) == today:
                    midnight = datetime(today.year, today.month, today.day, tzinfo=tz)
                    today_events.append((midnight, e))
            except Exception:
                pass

    today_events.sort(key=lambda x: x[0])
    lines = ["📅 *Today's Schedule*"]
    if not today_events:
        lines.append("No events today.")
    else:
        for dt_local, e in today_events:
            title = e.get("summary", "Untitled")
            # All-day events land at midnight; show as "All day"
            if dt_local.hour == 0 and dt_local.minute == 0:
                time_str = "All day"
            else:
                time_str = dt_local.strftime("%I:%M %p").lstrip("0")
            lines.append(f"• {time_str} — {title}")
    return "\n".join(lines)


def _section_tasks(tasks: list[dict], today: date) -> str:
    overdue: list[tuple[date, dict]] = []
    due_today: list[dict] = []

    for t in tasks:
        if t.get("status") == "completed" or not t.get("due"):
            continue
        try:
            task_date = parse_dt(t["due"]).date()
            if task_date < today:
                overdue.append((task_date, t))
            elif task_date == today:
                due_today.append(t)
        except Exception:
            pass

    if not overdue and not due_today:
        return "✅ *Tasks*\nAll caught up! 🎉"

    lines = ["✅ *Tasks*"]
    if overdue:
        lines.append("⚠️ _Overdue:_")
        for task_date, t in sorted(overdue, key=lambda x: x[0]):
            due_str = task_date.strftime("%b %-d")
            lines.append(f"  • {t['title']} _(was due {due_str})_")
    if due_today:
        lines.append("_Due today:_")
        for t in due_today:
            lines.append(f"  • {t['title']}")
    return "\n".join(lines)


def _section_projects(projects: list[dict]) -> str:
    if not projects:
        return ""
    _emoji = {"active": "🟢", "paused": "🟡", "complete": "✅", "archived": "⚫"}
    lines = ["🗂 *Top Projects*"]
    for p in projects[:3]:
        emoji = _emoji.get(p["status"], "⚪")
        due = f" · due {p['due_date']}" if p.get("due_date") else ""
        lines.append(f"  {emoji} {p['name']}{due}")
    return "\n".join(lines)


def _get_motivation() -> str:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.claude_model,
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": (
                "Write one short, original motivational sentence for starting the workday. "
                "Plain text only — no quotation marks, no attribution."
            ),
        }],
    )
    return resp.content[0].text.strip()


# ── Briefing builder ──────────────────────────────────────────────────────────

async def _build_briefing(tz) -> str:
    now = datetime.now(tz)
    today = now.date()
    day_str = now.strftime(f"%A, %B {now.day}, %Y")

    parts: list[str] = [f"🌅 *Good morning!*\n📅 {day_str}"]

    # Weather
    if settings.weather_city:
        try:
            section = _section_weather(settings.weather_city, settings.weather_country)
            if section:
                parts.append(section)
        except Exception as exc:
            logger.warning("Briefing weather failed: %s", exc)

    # Emails — top 5 unread
    try:
        emails = gmail.list_unread(max_results=5)
        parts.append(_section_emails(emails))
    except Exception as exc:
        logger.warning("Briefing emails failed: %s", exc)

    # Calendar — today's events
    try:
        events = gcalendar.list_events(days=1)
        parts.append(_section_calendar(events, tz))
    except Exception as exc:
        logger.warning("Briefing calendar failed: %s", exc)

    # Tasks — overdue + due today
    try:
        tasks = gtasks.list_tasks(max_results=50)
        parts.append(_section_tasks(tasks, today))
    except Exception as exc:
        logger.warning("Briefing tasks failed: %s", exc)

    # Projects — top 3 active
    try:
        active = projects_db.list_projects(status="active")
        section = _section_projects(active)
        if section:
            parts.append(section)
    except Exception as exc:
        logger.warning("Briefing projects failed: %s", exc)

    # Motivational closing
    try:
        motivation = _get_motivation()
        parts.append(f"💬 _{motivation}_")
    except Exception as exc:
        logger.warning("Briefing motivation failed: %s", exc)

    text = "\n\n".join(parts)
    if len(text) > 4000:
        text = text[:3980] + "\n\n_...truncated_"
    return text


# ── Public entry point (used by /briefing command) ───────────────────────────

async def build_briefing() -> str:
    """Build and return the full briefing text in the configured timezone."""
    tz = pytz.timezone(settings.timezone)
    return await _build_briefing(tz)


# ── Scheduler entry point ─────────────────────────────────────────────────────

async def _send_briefing(bot, telegram_id: int):
    logger.info("Sending daily briefing to user %s", telegram_id)
    try:
        tz = pytz.timezone(settings.timezone)
        text = await _build_briefing(tz)
        await db.save_briefing(telegram_id, text)
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
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
