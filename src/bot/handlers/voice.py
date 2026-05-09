import logging
import os
import tempfile
from telegram import Update
from telegram.ext import ContextTypes

from ...config import settings
from ...memory.database import db
from ...ai.claude_client import claude_client
from ...utils.transcription import transcribe_audio
from ...utils.formatting import truncate

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int) -> bool:
    allowed = settings.allowed_user_ids()
    return not allowed or user_id in allowed


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Sorry, you're not authorized to use this bot.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    await db.upsert_user(user.id, user.username or "", user.first_name or "")

    voice_file = await update.message.voice.get_file()
    tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        await voice_file.download_to_drive(tmp_path)
        transcript = transcribe_audio(tmp_path)
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        await update.message.reply_text("Sorry, I couldn't transcribe that voice message.")
        return
    finally:
        os.unlink(tmp_path)

    if not transcript:
        await update.message.reply_text("Sorry, I couldn't make out any speech in that message.")
        return

    # Echo the transcript so the user can confirm what was heard
    await update.message.reply_text(
        f"_Heard: {transcript}_", parse_mode="Markdown"
    )

    history = await db.get_recent_messages(user.id, limit=settings.conversation_window)
    response = await claude_client.chat(
        telegram_id=user.id,
        user_message=transcript,
        conversation_history=history,
    )

    await db.save_message(user.id, "user", transcript)
    await db.save_message(user.id, "assistant", response)
    await update.message.reply_text(truncate(response), parse_mode="Markdown")
