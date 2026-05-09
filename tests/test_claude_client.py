import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_chat_no_tool_use():
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Hello! How can I help you today?"
    mock_response.content = [text_block]

    with patch("src.ai.claude_client.anthropic.Anthropic") as mock_cls, \
         patch("src.ai.claude_client.context_retriever") as mock_ctx:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        mock_ctx.get_relevant_context = AsyncMock(return_value="")
        mock_ctx.store_message = AsyncMock()

        from src.ai.claude_client import ClaudeClient
        client = ClaudeClient()
        result = await client.chat(
            telegram_id=123,
            user_message="Hello",
            conversation_history=[],
        )
        assert "Hello" in result or len(result) > 0
        mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_chat_with_tool_use():
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "tool_abc123"
    tool_block.name = "tasks_list"
    tool_block.input = {"max_results": 5}
    tool_response.content = [tool_block]

    final_response = MagicMock()
    final_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Here are your tasks."
    final_response.content = [text_block]

    with patch("src.ai.claude_client.anthropic.Anthropic") as mock_cls, \
         patch("src.ai.claude_client.dispatch_tool") as mock_dispatch, \
         patch("src.ai.claude_client.context_retriever") as mock_ctx:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [tool_response, final_response]
        mock_cls.return_value = mock_client
        mock_dispatch.return_value = [{"id": "t1", "title": "Buy milk"}]
        mock_ctx.get_relevant_context = AsyncMock(return_value="")
        mock_ctx.store_message = AsyncMock()

        from src.ai.claude_client import ClaudeClient
        client = ClaudeClient()
        result = await client.chat(123, "List my tasks", [])
        mock_dispatch.assert_called_once_with("tasks_list", {"max_results": 5})
        assert "tasks" in result.lower() or len(result) > 0


@pytest.mark.asyncio
async def test_chat_builds_history():
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "Got it."
    mock_response.content = [text_block]

    history = [
        {"role": "user", "content": "Previous question"},
        {"role": "assistant", "content": "Previous answer"},
    ]

    with patch("src.ai.claude_client.anthropic.Anthropic") as mock_cls, \
         patch("src.ai.claude_client.context_retriever") as mock_ctx:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        mock_ctx.get_relevant_context = AsyncMock(return_value="")
        mock_ctx.store_message = AsyncMock()

        from src.ai.claude_client import ClaudeClient
        client = ClaudeClient()
        await client.chat(123, "Follow-up question", history)

        call_kwargs = mock_client.messages.create.call_args[1]
        messages_sent = call_kwargs["messages"]
        # Should have 2 history messages + 1 current = 3
        assert len(messages_sent) == 3
        assert messages_sent[-1]["content"] == "Follow-up question"
