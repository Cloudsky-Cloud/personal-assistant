"""Proactive fitness alerts: low-sleep warning, elevated HR, weekly trend summary."""
import logging
from datetime import date, datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from ..memory.database import db
from ..integrations.google_fit import google_fit
from ..integrations.gcalendar import gcalendar

logger = logging.getLogger(__name__)

_LOW_SLEEP_THRESHOLD_MIN = 360   # 6 hours
_ELEVATED_HR_RATIO = 1.20        # 20% above 7-day average
_ELEVATED_HR_ABSOLUTE = 85       # alert if HR ≥ this even without history


# ── Low sleep alert (7 AM daily) ──────────────────────────────────────────────

async def _check_low_sleep(bot):
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return

    try:
        sleep = google_fit.get_sleep()
    except Exception as exc:
        logger.warning("Fitness alert: sleep fetch failed: %s", exc)
        return

    total_min = sleep.get("total_minutes", 0) or 0
    if total_min >= _LOW_SLEEP_THRESHOLD_MIN:
        return  # sleep is fine

    h, m = sleep.get("hours", 0) or 0, sleep.get("minutes", 0) or 0
    sleep_str = f"{h}h {m}m"

    # Count today's calendar events
    event_count = 0
    try:
        events = gcalendar.list_events(days=1)
        tz = pytz.timezone(settings.timezone)
        today = datetime.now(tz).date()
        for e in events:
            start_str = e.get("start", "")
            if not start_str:
                continue
            try:
                from dateutil.parser import parse as parse_dt
                dt = parse_dt(start_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.astimezone(tz).date() == today:
                    event_count += 1
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Fitness alert: calendar fetch failed: %s", exc)

    event_note = (
        f"Your schedule has *{event_count} meeting{'s' if event_count != 1 else ''}* today."
        if event_count
        else "Check your schedule and consider a lighter day."
    )

    msg = (
        f"⚠️ *Low Sleep Alert*\n"
        f"You only got *{sleep_str}* of sleep last night.\n\n"
        f"{event_note}"
        f"\n\nWant me to help reschedule any non-critical meetings?"
    )

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Low sleep alert send failed for user %s: %s", uid, exc)


# ── Elevated HR alert (9 AM daily) ───────────────────────────────────────────

async def _check_elevated_hr(bot):
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return

    latest = await db.get_latest_energy_score()
    if not latest:
        return

    today_str = date.today().isoformat()
    # Only act on today's or yesterday's data
    if latest["date"] < str(date.today().replace(day=date.today().day - 1)):
        return

    bpm = latest.get("heart_rate_bpm")
    if not bpm:
        return

    # Get 7-day history to compute average HR
    history = await db.get_energy_scores(days=7)
    hr_values = [r["heart_rate_bpm"] for r in history if r.get("heart_rate_bpm") and r["date"] != latest["date"]]

    alert_reason = None
    if hr_values:
        avg_hr = sum(hr_values) / len(hr_values)
        if bpm >= avg_hr * _ELEVATED_HR_RATIO:
            alert_reason = f"significantly above your recent average ({round(avg_hr)} bpm)"
    if alert_reason is None and bpm >= _ELEVATED_HR_ABSOLUTE:
        alert_reason = "above the normal resting range"

    if alert_reason is None:
        return

    msg = (
        f"⚠️ *Elevated Heart Rate*\n"
        f"Your resting heart rate today is *{bpm} bpm* — {alert_reason}.\n\n"
        f"This may indicate stress, overtraining, or early illness. "
        f"Consider taking it easy and staying hydrated."
    )

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Elevated HR alert send failed for user %s: %s", uid, exc)


# ── Weekly health trend (Sunday 9 AM) ─────────────────────────────────────────

_LEVEL_EMOJI = {"low": "🔴", "medium": "🟡", "high": "🟢"}
_DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_weekly_trend(scores: list[dict]) -> str:
    if not scores:
        return ""

    # scores is newest-first; reverse to chronological
    rows = list(reversed(scores))

    lines = ["📊 *Weekly Health Summary*", ""]

    for r in rows:
        try:
            d = date.fromisoformat(r["date"])
            day_label = f"{_DAY_ABBR[d.weekday()]} {d.month}/{d.day}"
        except Exception:
            day_label = r["date"]

        emoji = _LEVEL_EMOJI.get(r.get("level", "medium"), "⚪")
        sc = r.get("score", 0)

        parts = [f"*{day_label}*  {emoji} {sc}"]
        if r.get("sleep_hours") is not None:
            parts.append(f"Sleep {r['sleep_hours']}h {r.get('sleep_minutes', 0)}m")
        if r.get("heart_rate_bpm"):
            parts.append(f"HR {r['heart_rate_bpm']}")
        if r.get("steps"):
            parts.append(f"Steps {r['steps']:,}")

        lines.append(" · ".join(parts))

    # Aggregates
    all_scores = [r["score"] for r in rows if r.get("score") is not None]
    avg_score = round(sum(all_scores) / len(all_scores)) if all_scores else None

    sleep_vals = [r["sleep_hours"] for r in rows if r.get("sleep_hours") is not None]
    avg_sleep_h = round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None

    hr_vals = [r["heart_rate_bpm"] for r in rows if r.get("heart_rate_bpm")]
    avg_hr = round(sum(hr_vals) / len(hr_vals)) if hr_vals else None

    lines.append("")
    if avg_score is not None:
        avg_emoji = _LEVEL_EMOJI.get("high" if avg_score >= 71 else ("medium" if avg_score >= 40 else "low"), "⚪")
        lines.append(f"📈 Average score: *{avg_score}/100* {avg_emoji}")
    if avg_sleep_h is not None:
        lines.append(f"😴 Average sleep: *{avg_sleep_h}h*")
    if avg_hr is not None:
        lines.append(f"❤️ Average resting HR: *{avg_hr} bpm*")

    low_days = sum(1 for r in rows if r.get("level") == "low")
    high_days = sum(1 for r in rows if r.get("level") == "high")

    lines.append("")
    if low_days >= 4:
        lines.append(f"💡 You had *{low_days} low-energy days* this week. Prioritise sleep and recovery this weekend.")
    elif low_days >= 2:
        lines.append(f"💡 You had *{low_days} low-energy days* this week. Watch your sleep schedule.")
    elif high_days >= 5:
        lines.append("🌟 Excellent week! Consistent high energy across most days.")
    elif avg_score and avg_score >= 60:
        lines.append("👍 Solid week overall. Keep it up!")
    else:
        lines.append("💡 Focus on sleep consistency to boost your energy scores next week.")

    return "\n".join(lines)


async def _send_weekly_summary(bot):
    user_ids = await db.get_all_user_ids()
    if not user_ids:
        return

    scores = await db.get_energy_scores(days=7)
    if not scores:
        logger.info("Weekly summary: no energy scores recorded yet")
        return

    text = _format_weekly_trend(scores)
    if not text:
        return

    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="Markdown")
        except Exception as exc:
            logger.error("Weekly summary send failed for user %s: %s", uid, exc)


# ── Scheduler registration ────────────────────────────────────────────────────

def schedule_fitness_alerts(scheduler: AsyncIOScheduler, bot):
    tz = pytz.timezone(settings.timezone)

    async def low_sleep_job():
        await _check_low_sleep(bot)

    async def elevated_hr_job():
        await _check_elevated_hr(bot)

    async def weekly_summary_job():
        await _send_weekly_summary(bot)

    scheduler.add_job(
        low_sleep_job,
        CronTrigger(hour=7, minute=0, timezone=tz),
        id="fitness_low_sleep_alert",
        replace_existing=True,
    )

    scheduler.add_job(
        elevated_hr_job,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="fitness_elevated_hr_alert",
        replace_existing=True,
    )

    scheduler.add_job(
        weekly_summary_job,
        CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=tz),
        id="fitness_weekly_summary",
        replace_existing=True,
    )

    logger.info(
        "Fitness alerts scheduled: low-sleep@07:00, elevated-HR@09:00, weekly-summary@Sun 09:00 %s",
        settings.timezone,
    )
