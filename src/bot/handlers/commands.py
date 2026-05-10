import io
import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.formatting import format_task_list, truncate
from ...scheduler.briefing import build_briefing

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    allowed = settings.allowed_user_ids()
    return not allowed or user_id in allowed


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        f"Hello {user.first_name}! I'm your personal assistant.\n\n"
        "I can help you with:\n"
        "• 📧 Reading and managing emails\n"
        "• 📅 Calendar events and reminders\n"
        "• 📂 Finding Drive files\n"
        "• ✅ Creating and prioritizing tasks\n"
        "• 🔍 Searching the web\n"
        "• 🎙 Voice responses\n\n"
        "Send text or a voice note, or use a command:\n"
        "/briefing — /voice — /tasks — /help"
    )


async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    text = await build_briefing()
    await update.message.reply_text(text, parse_mode="Markdown")


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process a message and respond with both text and an MP3 audio file."""
    user = update.effective_user
    logger.info("/voice received from user %s", user.id)

    if not _is_allowed(user.id):
        logger.warning("/voice user %s is not allowed", user.id)
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    query = " ".join(context.args or []).strip()
    logger.info("/voice query: %r", query)
    if not query:
        await update.message.reply_text(
            "Usage: `/voice <your message>`\n"
            "Example: `/voice what's on my calendar today`",
            parse_mode="Markdown",
        )
        return

    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    logger.info("/voice calling Claude...")
    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=query,
        conversation_history=history,
    )
    logger.info("/voice Claude response: %d chars", len(response))
    await db.save_message(user.id, "user", query)
    await db.save_message(user.id, "assistant", response)

    # Always send the text response first
    await update.message.reply_text(truncate(response), parse_mode="Markdown")
    logger.info("/voice text reply sent")

    # Then synthesise and send audio
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_voice")
    logger.info("/voice calling Google TTS...")
    try:
        from ...integrations.gtts import text_to_speech
        audio_bytes = text_to_speech(response)
        logger.info("/voice TTS returned %d bytes", len(audio_bytes))
        buf = io.BytesIO(audio_bytes)
        buf.name = "response.mp3"
        await update.message.reply_audio(audio=buf, title="Voice Response")
        logger.info("/voice audio sent successfully")
    except Exception:
        logger.exception("/voice TTS failed")
        await update.message.reply_text(
            "_(Could not generate audio — see text response above)_",
            parse_mode="Markdown",
        )


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    tasks = await db.get_pending_tasks(user.id)
    msg = format_task_list(tasks)
    await update.message.reply_text(msg, parse_mode="Markdown")


async def fitdebug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dump raw Google Fit data sources and sessions for debugging."""
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    from ...integrations.google_fit import google_fit

    lines: list[str] = []

    # ── Data sources ──────────────────────────────────────────────────────────
    lines.append("*DATA SOURCES*")
    try:
        sources = google_fit.debug_data_sources()
        if not sources:
            lines.append("_(none found)_")
        else:
            for ds in sources:
                stream_id  = ds.get("dataStreamId", "?")
                type_name  = ds.get("dataType", {}).get("name", "?")
                device     = ds.get("device", {}).get("model", "")
                app        = ds.get("application", {}).get("packageName", "")
                source_tag = device or app or "unknown"
                lines.append(f"`{type_name}`\n  {source_tag}\n  `{stream_id}`")
    except Exception as exc:
        lines.append(f"Error: {exc}")

    lines.append("")

    # ── Sessions (last 7 days) ────────────────────────────────────────────────
    lines.append("*SESSIONS (last 7 days)*")
    try:
        sessions = google_fit.debug_sessions(days=7)
        if not sessions:
            lines.append("_(none found)_")
        else:
            for s in sessions:
                s_ms   = int(s.get("startTimeMillis", 0))
                e_ms   = int(s.get("endTimeMillis", 0))
                dur_m  = (e_ms - s_ms) // 60_000
                from datetime import datetime, timezone
                start_str = datetime.fromtimestamp(s_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                atype  = s.get("activityType", "?")
                name   = s.get("name", "")
                app    = s.get("application", {}).get("packageName", "")
                lines.append(
                    f"`{start_str}` type={atype} dur={dur_m}m\n"
                    f"  name={name!r} app={app}"
                )
    except Exception as exc:
        lines.append(f"Error: {exc}")

    # Split into chunks ≤4000 chars (Telegram limit)
    text = "\n".join(lines)
    chunk_size = 3800
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/briefing — Full morning briefing now\n"
        "/voice <message> — Reply with text + audio\n"
        "/tasks — Show your prioritized task list\n"
        "/fitdebug — Raw Google Fit data sources + sessions\n"
        "/help — This help message\n\n"
        "Or send any text or voice message.",
        parse_mode="Markdown",
    )
