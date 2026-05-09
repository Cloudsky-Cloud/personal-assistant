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
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    query = " ".join(context.args or []).strip()
    if not query:
        await update.message.reply_text(
            "Usage: `/voice <your message>`\n"
            "Example: `/voice what's on my calendar today`",
            parse_mode="Markdown",
        )
        return

    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=query,
        conversation_history=history,
    )
    await db.save_message(user.id, "user", query)
    await db.save_message(user.id, "assistant", response)

    # Always send the text response first
    await update.message.reply_text(truncate(response), parse_mode="Markdown")

    # Then synthesise and send audio
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_voice")
    try:
        from ...integrations.gtts import text_to_speech
        audio_bytes = text_to_speech(response)
        buf = io.BytesIO(audio_bytes)
        buf.name = "response.mp3"
        await update.message.reply_audio(audio=buf, title="Voice Response")
    except Exception as exc:
        logger.error("Voice synthesis failed: %s", exc)
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


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands:*\n"
        "/start — Welcome message\n"
        "/briefing — Full morning briefing now\n"
        "/voice <message> — Reply with text + audio\n"
        "/tasks — Show your prioritized task list\n"
        "/help — This help message\n\n"
        "Or send any text or voice message.",
        parse_mode="Markdown",
    )
