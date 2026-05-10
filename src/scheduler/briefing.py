import logging
import re
from datetime import date, datetime, timedelta, timezone

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
from ..integrations.google_fit import GoogleFit, google_fit

logger = logging.getLogger(__name__)


# ── Email filtering ───────────────────────────────────────────────────────────

# Gmail query used to pre-filter server-side before fetching message bodies.
# Strips promotions, social network pings, automated updates, and mailing lists.
_EMAIL_QUERY = (
    "is:unread "
    "-category:promotions "
    "-category:social "
    "-category:updates "
    "-category:forums"
)

# Local parts that are definitively not a real person.
_NOREPLY_LOCAL_PARTS = frozenset({
    "no-reply", "noreply", "donotreply", "do-not-reply", "do_not_reply",
    "notification", "notifications",
    "alert", "alerts",
    "security",
    "mailer", "mailer-daemon", "mailerdaemon",
    "postmaster", "bounce", "bounces",
    "newsletter", "newsletters",
    "marketing", "promotions", "promo",
    "automated", "automailer", "automatic",
    "digest", "updates", "unsubscribe",
})

# Domains that only ever send automated mail.
_AUTOMATED_DOMAINS = frozenset({
    # Code / DevOps
    "github.com", "githubusercontent.com",
    "gitlab.com", "bitbucket.org",
    # Professional / social networks
    "linkedin.com", "bounce.linkedin.com",
    "twitter.com", "x.com",
    "facebook.com", "facebookmail.com",
    "instagram.com", "pinterest.com",
    "reddit.com", "tiktok.com", "youtube.com",
    # Productivity SaaS
    "slack.com", "notion.so", "trello.com",
    "asana.com", "monday.com",
    "atlassian.net", "jira.atlassian.com",
    # Email delivery / marketing platforms
    "mailchimp.com", "mailgun.org", "sendgrid.net",
    "amazonses.com", "ses.amazonaws.com",
    "mandrillapp.com", "sparkpostmail.com",
    "constantcontact.com", "hubspot.com",
    "klaviyo.com", "mailerlite.com",
    "convertkit.com", "beehiiv.com",
    # Publishing / newsletters
    "substack.com", "medium.com",
    # Google automated mail
    "accounts.google.com", "no-reply.accounts.google.com",
})

# Subdomains of these roots are also automated (e.g. notifications.github.com).
_AUTOMATED_DOMAIN_ROOTS = (
    "github.com", "linkedin.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com",
    "atlassian.net", "amazonses.com",
)

# Subject/snippet keywords that signal an email needs immediate attention.
_URGENT_SUBJECT_WORDS = frozenset({
    "urgent", "asap", "immediately", "action required",
    "deadline", "critical", "time sensitive", "time-sensitive",
    "overdue", "past due",
})


def _is_automated_sender(from_str: str) -> bool:
    """Return True if the sender is an automated/no-reply address, not a real person."""
    m = re.search(r"<([^>]+)>", from_str)
    addr = m.group(1).lower() if m else from_str.lower().strip()
    local, _, domain = addr.partition("@")
    if not domain:
        return False
    if local in _NOREPLY_LOCAL_PARTS:
        return True
    if "noreply" in local or "no-reply" in local or "donotreply" in local:
        return True
    if domain in _AUTOMATED_DOMAINS:
        return True
    for root in _AUTOMATED_DOMAIN_ROOTS:
        if domain.endswith("." + root):
            return True
    return False


def _filter_emails(emails: list[dict]) -> list[dict]:
    """Return only emails that appear to be from real people."""
    return [e for e in emails if not _is_automated_sender(e.get("from") or "")]


def _is_urgent_email(email: dict) -> bool:
    """Return True if the email subject or snippet contains urgency signals."""
    text = (
        (email.get("subject") or "") + " " + (email.get("snippet") or "")
    ).lower()
    return any(w in text for w in _URGENT_SUBJECT_WORDS)


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
        return "📬 *Unread Emails*\nNo emails from real people — inbox is clear! 🎉"
    lines = [f"📬 *Unread Emails ({len(emails)})*"]
    for e in emails:
        subject = (e.get("subject") or "No subject")[:60].strip()
        sender = _clean_sender(e.get("from") or "Unknown")[:40]
        snippet = (e.get("snippet") or "").strip()[:100]
        flag = " 🚨" if _is_urgent_email(e) else ""
        lines.append(f"• *{subject}*{flag}")
        lines.append(f"  From: {sender}")
        if snippet:
            lines.append(f"  _{snippet}_")
    return "\n".join(lines)


def _count_today_events(events: list[dict], tz, today: date) -> int:
    count = 0
    for e in events:
        start_str = e.get("start", "")
        if not start_str:
            continue
        try:
            dt = parse_dt(start_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.astimezone(tz).date() == today:
                count += 1
        except Exception:
            try:
                if date.fromisoformat(start_str) == today:
                    count += 1
            except Exception:
                pass
    return count


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


def _section_tasks(
    overdue: list[tuple[date, dict]],
    due_today: list[dict],
    due_this_week: list[tuple[date, dict]],
) -> str:
    if not overdue and not due_today and not due_this_week:
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
    if due_this_week:
        lines.append("_Due this week:_")
        for task_date, t in sorted(due_this_week, key=lambda x: x[0]):
            due_str = task_date.strftime("%a %-d")
            lines.append(f"  • {t['title']} _(due {due_str})_")
    return "\n".join(lines)


_HIGH_STAKES_KEYWORDS = frozenset({
    "interview", "presentation", "review", "board", "client",
    "performance", "evaluation", "demo", "pitch", "surgery", "procedure",
    "deposition", "hearing", "audit",
})


def _find_high_stakes_events(events: list[dict], tz) -> list[str]:
    today = datetime.now(tz).date()
    results = []
    for e in events:
        start_str = e.get("start", "")
        if not start_str:
            continue
        try:
            dt = parse_dt(start_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt_local = dt.astimezone(tz)
            if dt_local.date() != today:
                continue
            title = e.get("summary", "")
            lower = title.lower()
            is_high_stakes = (
                any(kw in lower for kw in _HIGH_STAKES_KEYWORDS)
                or len(e.get("attendees", [])) >= 3
            )
            if is_high_stakes:
                time_str = dt_local.strftime("%I:%M %p").lstrip("0")
                results.append(f"{time_str} — {title}")
        except Exception:
            pass
    return results


def _energy_alert_text(score: int, level: str, sleep: dict, hr: dict, events: list[dict], tz) -> str:
    if level == "low":
        h, m = sleep.get("hours", 0) or 0, sleep.get("minutes", 0) or 0
        sleep_str = f"{h}h {m}m" if sleep.get("hours") is not None else "unknown"
        bpm = hr.get("bpm")
        bpm_note = f" · ❤️ HR: {bpm} bpm (elevated)" if bpm and bpm > 80 else ""
        lines = [f"🔴 *Low Energy* (score: {score}/100)"]
        lines.append(f"Poor sleep detected ({sleep_str}){bpm_note}.")
        high_stakes = _find_high_stakes_events(events, tz)
        if high_stakes:
            lines.append(f"⚠️ High-stakes events today:")
            for ev in high_stakes[:3]:
                lines.append(f"  • {ev}")
        lines.append("💡 Defer non-critical tasks. Avoid major decisions before noon.")
        lines.append("🧠 Best focus window: 10–11 AM.")
        return "\n".join(lines)

    if level == "medium":
        lines = [f"🟡 *Average Recovery* (score: {score}/100)"]
        lines.append("Stay hydrated and take short breaks between meetings.")
        lines.append("🧠 Best focus window: 9–11 AM.")
        return "\n".join(lines)

    # high
    lines = [f"🟢 *Great Recovery!* (score: {score}/100)"]
    lines.append("Good day for deep work and important decisions.")
    lines.append("🧠 Prime hours: all morning — tackle your hardest tasks first.")
    return "\n".join(lines)


def _section_fitness(fit: dict, energy: dict, events: list[dict], tz) -> str:
    steps = fit.get("steps", {})
    sleep = fit.get("sleep", {})
    hr = fit.get("heart_rate", {})
    cal = fit.get("calories", {})
    active = fit.get("active_minutes", {})
    score = energy.get("score")
    level = energy.get("level", "medium")

    lines = ["💪 *Health & Fitness*"]

    if score is not None:
        level_emoji = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(level, "⚪")
        lines.append(f"🔋 Energy score: {score}/100 {level_emoji}")

    s = steps.get("steps")
    if s is not None:
        pct = steps.get("goal_pct", 0)
        lines.append(f"👟 Steps: {s:,} ({pct}% of goal)")

    h, m = sleep.get("hours"), sleep.get("minutes")
    if h is not None:
        lines.append(f"😴 Sleep: {h}h {m}m")

    bpm = hr.get("bpm")
    if bpm:
        lines.append(f"❤️ Heart rate: {bpm} bpm")

    c = cal.get("calories")
    if c:
        lines.append(f"🔥 Calories: {c:,}")

    am = active.get("minutes")
    if am is not None:
        lines.append(f"⚡ Active minutes: {am}")

    if len(lines) == 1:
        return ""

    if score is not None:
        lines.append("")
        lines.append(_energy_alert_text(score, level, sleep, hr, events, tz))

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


def _classify_workload(overdue_count: int, email_count: int, event_count: int) -> str:
    score = overdue_count * 2 + email_count + event_count
    if score >= 8:
        return "heavy"
    if score >= 4:
        return "moderate"
    return "light"


def _get_motivation(day_name: str, workload: str) -> str:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = (
        f"Today is {day_name} and the user's workload is {workload}. "
        "Write one short, original motivational sentence tailored to this context. "
        "Plain text only — no quotation marks, no attribution, no emoji."
    )
    resp = client.messages.create(
        model=settings.claude_model,
        max_tokens=80,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


# ── Briefing builder ──────────────────────────────────────────────────────────

async def _build_briefing(tz) -> str:
    now = datetime.now(tz)
    today = now.date()
    week_end = today + timedelta(days=6)
    day_str = now.strftime(f"%A, %B {now.day}, %Y")

    # ── Gather raw data ───────────────────────────────────────────────────────
    human_emails: list[dict] = []
    all_events: list[dict] = []
    all_tasks: list[dict] = []
    active_projects: list[dict] = []
    fit_data: dict = {}
    energy_data: dict = {}

    try:
        raw = gmail.search(_EMAIL_QUERY, max_results=15)
        human_emails = _filter_emails(raw)[:5]
        logger.info("Briefing emails: %d fetched, %d after filtering", len(raw), len(human_emails))
    except Exception as exc:
        logger.warning("Briefing emails failed: %s", exc)

    try:
        all_events = gcalendar.list_events(days=1)
    except Exception as exc:
        logger.warning("Briefing calendar failed: %s", exc)

    try:
        all_tasks = gtasks.list_tasks(max_results=50)
    except Exception as exc:
        logger.warning("Briefing tasks failed: %s", exc)

    try:
        active_projects = projects_db.list_projects(status="active")
    except Exception as exc:
        logger.warning("Briefing projects failed: %s", exc)

    try:
        fit_data = google_fit.get_summary()
        energy_data = GoogleFit.compute_energy_score(fit_data)
        sleep_d = fit_data.get("sleep", {})
        hr_d = fit_data.get("heart_rate", {})
        steps_d = fit_data.get("steps", {})
        active_d = fit_data.get("active_minutes", {})
        await db.save_energy_score(
            date_str=today.isoformat(),
            score=energy_data["score"],
            level=energy_data["level"],
            sleep_hours=sleep_d.get("hours"),
            sleep_minutes=sleep_d.get("minutes"),
            heart_rate_bpm=hr_d.get("bpm"),
            steps=steps_d.get("steps"),
            active_minutes=active_d.get("minutes"),
        )
        logger.info("Briefing fitness: score=%d (%s)", energy_data["score"], energy_data["level"])
    except Exception as exc:
        logger.warning("Briefing fitness failed: %s", exc)

    # ── Bucket tasks ──────────────────────────────────────────────────────────
    overdue: list[tuple[date, dict]] = []
    due_today: list[dict] = []
    due_this_week: list[tuple[date, dict]] = []

    for t in all_tasks:
        if t.get("status") == "completed" or not t.get("due"):
            continue
        try:
            task_date = parse_dt(t["due"]).date()
            if task_date < today:
                overdue.append((task_date, t))
            elif task_date == today:
                due_today.append(t)
            elif task_date <= week_end:
                due_this_week.append((task_date, t))
        except Exception:
            pass

    # ── Compute summary stats ─────────────────────────────────────────────────
    email_count = len(human_emails)
    event_count = _count_today_events(all_events, tz, today)
    overdue_count = len(overdue)
    urgent_emails = [e for e in human_emails if _is_urgent_email(e)]

    # ── Greeting + one-line summary ───────────────────────────────────────────
    parts: list[str] = []

    stat_parts: list[str] = []
    if email_count:
        stat_parts.append(f"{email_count} email{'s' if email_count != 1 else ''}")
    if event_count:
        stat_parts.append(f"{event_count} meeting{'s' if event_count != 1 else ''}")
    if overdue_count:
        stat_parts.append(f"⚠️ {overdue_count} overdue task{'s' if overdue_count != 1 else ''}")
    elif due_today:
        n = len(due_today)
        stat_parts.append(f"{n} task{'s' if n != 1 else ''} due today")

    greeting = f"🌅 *Good morning!*\n📅 {day_str}"
    if stat_parts:
        greeting += f"\n📊 You have {', '.join(stat_parts)} today."
    parts.append(greeting)

    # ── Urgency alert (prominent, right after greeting) ───────────────────────
    alert_lines: list[str] = []
    if overdue_count:
        n = overdue_count
        alert_lines.append(f"⚠️ *{n} overdue task{'s' if n != 1 else ''}* — needs attention!")
    for e in urgent_emails[:2]:
        subject = (e.get("subject") or "")[:50]
        sender = _clean_sender(e.get("from") or "")[:30]
        alert_lines.append(f"🚨 *Urgent email* from {sender}: _{subject}_")
    if alert_lines:
        parts.append("\n".join(alert_lines))

    # ── Sections ──────────────────────────────────────────────────────────────
    if settings.weather_city:
        try:
            section = _section_weather(settings.weather_city, settings.weather_country)
            if section:
                parts.append(section)
        except Exception as exc:
            logger.warning("Briefing weather failed: %s", exc)

    try:
        section = _section_fitness(fit_data, energy_data, all_events, tz)
        if section:
            parts.append(section)
    except Exception as exc:
        logger.warning("Briefing fitness section failed: %s", exc)

    parts.append(_section_emails(human_emails))
    parts.append(_section_calendar(all_events, tz))
    parts.append(_section_tasks(overdue, due_today, due_this_week))

    section = _section_projects(active_projects)
    if section:
        parts.append(section)

    # ── Motivational closing (day + workload aware) ───────────────────────────
    workload = _classify_workload(overdue_count, email_count, event_count)
    try:
        motivation = _get_motivation(now.strftime("%A"), workload)
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
