import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_user.username = "testuser"
    update.effective_user.first_name = "Test"
    update.effective_chat.id = 12345
    update.message.reply_text = AsyncMock()
    update.message.text = "List my emails"
    return update


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_message_handler_allowed_user(mock_update, mock_context):
    with patch("src.bot.handlers.messages.settings") as mock_s, \
         patch("src.bot.handlers.messages.db") as mock_db, \
         patch("src.bot.handlers.messages.claude_client") as mock_claude:
        mock_s.telegram_allowed_users = [12345]
        mock_s.conversation_window = 20
        mock_db.upsert_user = AsyncMock()
        mock_db.save_message = AsyncMock()
        mock_db.get_recent_messages = AsyncMock(return_value=[])
        mock_claude.chat = AsyncMock(return_value="Here are your emails.")

        from src.bot.handlers.messages import handle_message
        await handle_message(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "emails" in call_args.lower()


@pytest.mark.asyncio
async def test_message_handler_blocked_user(mock_update, mock_context):
    with patch("src.bot.handlers.messages.settings") as mock_s:
        mock_s.telegram_allowed_users = [99999]  # 12345 not in list

        from src.bot.handlers.messages import handle_message
        await handle_message(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, you're not authorized to use this bot."
        )


@pytest.mark.asyncio
async def test_start_command_allowed_user(mock_update, mock_context):
    with patch("src.bot.handlers.commands.settings") as mock_s, \
         patch("src.bot.handlers.commands.db") as mock_db:
        mock_s.telegram_allowed_users = [12345]
        mock_db.upsert_user = AsyncMock()

        from src.bot.handlers.commands import start_command
        await start_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "Hello Test" in reply


@pytest.mark.asyncio
async def test_start_command_blocked_user(mock_update, mock_context):
    with patch("src.bot.handlers.commands.settings") as mock_s:
        mock_s.telegram_allowed_users = [99999]

        from src.bot.handlers.commands import start_command
        await start_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once_with(
            "Sorry, you're not authorized to use this bot."
        )


@pytest.mark.asyncio
async def test_tasks_command_empty(mock_update, mock_context):
    with patch("src.bot.handlers.commands.settings") as mock_s, \
         patch("src.bot.handlers.commands.db") as mock_db:
        mock_s.telegram_allowed_users = [12345]
        mock_db.get_pending_tasks = AsyncMock(return_value=[])
        mock_context.bot.send_chat_action = AsyncMock()

        from src.bot.handlers.commands import tasks_command
        await tasks_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "No pending tasks" in reply
