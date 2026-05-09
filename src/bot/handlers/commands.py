import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.formatting import format_task_list, truncate

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
        "• ✅ Creating and prioritizing tasks\n\n"
        "Just send me a message or a voice note.\n\n"
        "Commands: /briefing — /tasks — /help"
    )


async def briefing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=(
            "Give me my daily briefing: "
            "1) Summarize important unread emails from the last 24 hours. "
            "2) List today's calendar events. "
            "3) Show my top 5 tasks by priority. "
            "Keep it concise."
        ),
        conversation_history=[],
    )
    await update.message.reply_text(truncate(response), parse_mode="Markdown")


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
        "/briefing — Get your daily briefing now\n"
        "/tasks — Show your prioritized task list\n"
        "/help — This help message\n\n"
        "Or just send any text or voice message and I'll handle it.",
        parse_mode="Markdown",
    )
