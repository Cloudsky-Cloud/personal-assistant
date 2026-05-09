import json
import logging
from datetime import date
from typing import Optional

import anthropic

from ..config import settings
from .tools import TOOL_SCHEMAS, dispatch_tool
from ..memory.context_retriever import context_retriever

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a personal assistant with access to Gmail, Google Calendar, Google Drive, and Google Tasks.
You are helpful, concise, and proactive. You remember past conversations and user preferences.

Your Gmail capabilities include: reading emails, searching emails, marking as read, and SENDING emails.
When the user asks you to send or write an email, use the gmail_send_email tool immediately — \
you are fully authorized to send emails on the user's behalf.
If the user gives you a name instead of an email address, use contacts_lookup first. \
If contacts_lookup returns multiple matches, ask the user to clarify which one they mean before sending. \
If contacts_lookup finds no match, ask the user for the email address and offer to save it as a new contact.

Contacts database capabilities: contacts_lookup (search by name), contacts_upsert (add/update), \
contacts_list (show all contacts), contacts_delete (remove a contact). \
Use these when the user asks to manage their contacts.

Your Google Calendar capabilities include: listing events, searching events, and CREATING events.
When the user asks to schedule, add, or book anything on their calendar, use calendar_create_event immediately.
Convert all dates and times to ISO 8601 UTC format (e.g. 2026-05-10T14:00:00Z).
If no duration is given, default to 30 minutes (end = start + 30 min).
Confirm back with the event name, date, and time after creating it.

When the user asks you to do something with their files or tasks — use the available tools.
Only confirm before deleting.

You have a local projects database. Use the projects_* tools for any project or note management:
- projects_create: "add project X", "new project Y with due date Friday"
- projects_update: "mark X done" → status=complete; "update X status to paused"; "rename X to Y"
- projects_list: "show my projects", "what are my active projects", \
"what's due this week" → pass due_before=end-of-week ISO date, "show archived projects"
- projects_delete: "delete project X" (confirm first)
- projects_add_note: "add note to X: meeting went well", "note for X: ..."
- projects_get_notes: "show notes for X", "what are the X notes"
- projects_search: "find projects about marketing", "projects mentioning budget"

Format responses for Telegram: use Markdown, keep messages under 4000 characters.

Today's date: {date}

Relevant context from past conversations:
{context}
"""


class ClaudeClient:
    def __init__(self):
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def chat(
        self,
        telegram_id: int,
        user_message: str,
        conversation_history: list[dict],
        date_str: Optional[str] = None,
    ) -> str:
        if not date_str:
            date_str = date.today().isoformat()

        relevant_ctx = await context_retriever.get_relevant_context(
            telegram_id, user_message, n=5
        )
        system = _SYSTEM_PROMPT.format(
            date=date_str, context=relevant_ctx or "None"
        )

        messages = self._build_messages(conversation_history, user_message)
        response_text = await self._run_tool_loop(messages, system)

        # Persist exchange to vector memory
        msg_key = f"{telegram_id}_{date_str}_{len(messages)}"
        await context_retriever.store_message(
            telegram_id, "user", user_message, f"u_{msg_key}"
        )
        await context_retriever.store_message(
            telegram_id, "assistant", response_text, f"a_{msg_key}"
        )
        return response_text

    # ── Internal helpers ───────────────────────────────────────────────────

    def _build_messages(
        self, history: list[dict], user_message: str
    ) -> list[dict]:
        messages: list[dict] = []
        for m in history:
            role = m.get("role")
            if role == "user":
                messages.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                if m.get("tool_calls"):
                    messages.append({"role": "assistant", "content": m["tool_calls"]})
                else:
                    messages.append({"role": "assistant", "content": m["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def _run_tool_loop(self, messages: list[dict], system: str) -> str:
        for _ in range(10):  # max 10 tool-use iterations
            response = self._client.messages.create(
                model=settings.claude_model,
                max_tokens=4096,
                system=system,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info("Tool call: %s %s", block.name, block.input)
                        try:
                            result = dispatch_tool(block.name, block.input)
                        except Exception as exc:
                            logger.error("Tool %s failed: %s", block.name, exc)
                            result = {"error": str(exc)}
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            }
                        )
                # Append assistant's tool-use turn then the tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason — return whatever text we have
                return self._extract_text(response)

        return "I had trouble completing that request. Please try again."

    def _extract_text(self, response) -> str:
        parts = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(parts).strip() or "Done."


claude_client = ClaudeClient()
