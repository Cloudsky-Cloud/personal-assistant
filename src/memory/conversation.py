from .database import db
from ..config import settings


class ConversationManager:
    async def get_history(self, telegram_id: int) -> list[dict]:
        """Return recent messages formatted for the Claude messages API."""
        raw = await db.get_recent_messages(telegram_id, limit=settings.conversation_window)
        messages = []
        for m in raw:
            if m["role"] == "user":
                messages.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                if m.get("tool_calls"):
                    messages.append({"role": "assistant", "content": m["tool_calls"]})
                else:
                    messages.append({"role": "assistant", "content": m["content"]})
        return messages

    async def add_exchange(self, telegram_id: int, user_text: str, assistant_text: str):
        await db.save_message(telegram_id, "user", user_text)
        await db.save_message(telegram_id, "assistant", assistant_text)


conversation_manager = ConversationManager()
