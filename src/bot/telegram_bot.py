from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)
from ..config import settings
from .handlers.commands import (
    start_command, briefing_command, voice_command, tasks_command, help_command,
)
from .handlers.messages import handle_message
from .handlers.voice import handle_voice


def build_application() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("briefing", briefing_command))
    app.add_handler(CommandHandler("voice", voice_command))
    app.add_handler(CommandHandler("tasks", tasks_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
