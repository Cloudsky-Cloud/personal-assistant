import logging
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.formatting import truncate

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    allowed = settings.allowed_user_ids()
    return not allowed or user_id in allowed


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    await db.upsert_user(user.id, user.username or "", user.first_name or "")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    text = update.message.text or ""
    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)

    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=text,
        conversation_history=history,
    )

    await db.save_message(user.id, "user", text)
    await db.save_message(user.id, "assistant", response)

    await update.message.reply_text(truncate(response), parse_mode="Markdown")
