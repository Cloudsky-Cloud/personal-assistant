import asyncio
import json
import logging
from datetime import date
from typing import Optional

import anthropic

from ..config import settings
from .tools import TOOL_SCHEMAS, dispatch_tool
from ..memory.context_retriever import context_retriever
from ..integrations.gbrain import gbrain

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a personal assistant with access to Gmail, Google Calendar, Google Drive, Google Tasks, \
a contacts database, a projects database, and web search.
You are helpful, concise, and proactive. You remember past conversations and user preferences.

Your Gmail capabilities include: reading emails, searching emails, marking as read, and SENDING emails.
When the user asks you to send or write an email, use the gmail_send_email tool immediately — \
you are fully authorized to send emails on the user's behalf.
If the user gives you a name instead of an email address, use contacts_lookup first. \
If contacts_lookup returns multiple matches, ask the user to clarify which one they mean before sending. \
If contacts_lookup finds no match, ask the user for the email address and offer to save it as a new contact.

Contacts database capabilities: contacts_lookup (search by name — falls back to Google Contacts \
automatically if not found locally), contacts_upsert (add/update with full details — also saves to \
Google Contacts), contacts_list (show all contacts), contacts_delete (removes locally and from \
Google Contacts), contacts_sync (imports all Google Contacts into the local database).
contacts_upsert accepts: name, email, phone_mobile, phone_work, phone_home, address_street, \
address_city, address_country, company, notes, birthday (YYYY-MM-DD or MM-DD). \
When the user says things like "add Ahmed with email ahmed@gmail.com phone +1234567890 works at \
Acme lives in Dubai", extract all the fields and pass them in a single contacts_upsert call.

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

Web search capabilities:
- web_search: general questions ("what is X", "how does X work", "find articles about X", \
"look up X", "search for X"). Always include source URLs in your response.
- web_search_news: current events and recent news ("latest news on X", "what happened with X", \
"recent updates about X"). Always include source and date.
Use web search proactively whenever the question requires current or broad factual knowledge.

Long-term brain (GBrain) capabilities:
- brain_search: search your permanent memory for anything about a person, topic, or project. \
Use when the user asks "what do you know about X", "find everything about Y", \
"do you remember anything about Z", or any question that might have prior context.
- brain_write: store something permanently. Use immediately when the user says \
"remember that...", "note that...", "always remember...", or whenever a fact, \
decision, or preference clearly should be retained long-term. \
Provide a slug (e.g. "people/name", "topics/project") for structured pages.
- brain_think: deep multi-hop synthesis across all brain knowledge. Use for \
"what's the full picture on X?", "summarise everything about Y", \
"what do I know about this person?". Richer than brain_search — it reasons, \
not just retrieves. Provide an anchor slug when asking about a specific person or topic.
The long-term memory context above is pre-fetched automatically before each reply — \
use it to give informed, personalised answers without needing to call brain_search first.

Format responses for Telegram: use Markdown, keep messages under 4000 characters.

Today's date: {date}

Relevant context from past conversations:
{context}

Long-term memory (GBrain):
{brain_context}
"""


async def _fetch_brain_context(query: str) -> tuple[list, list]:
    """Return (pages, facts) from GBrain in parallel. Both empty if GBrain disabled."""
    pages, facts = await asyncio.gather(
        gbrain.query(query, limit=5),
        gbrain.recall(query, limit=8),
    )
    return pages, facts


async def _call_tool_with_retry(name: str, inp: dict, max_attempts: int = 3) -> dict:
    """Call dispatch_tool with exponential backoff. Returns an error dict after max_attempts."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await dispatch_tool(name, inp)
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                wait = 2 ** attempt  # 1 s, then 2 s
                logger.warning(
                    "Tool %s attempt %d/%d failed, retrying in %ds: %s",
                    name, attempt + 1, max_attempts, wait, exc,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "Tool %s failed after %d attempts: %s", name, max_attempts, exc
                )
    return {
        "error": (
            f"Tool '{name}' failed after {max_attempts} attempts. "
            f"Last error: {last_exc}"
        )
    }


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

        # Fetch short-term (ChromaDB) and long-term (GBrain) context in parallel
        relevant_ctx, (brain_pages, brain_facts) = await asyncio.gather(
            context_retriever.get_relevant_context(telegram_id, user_message, n=5),
            _fetch_brain_context(user_message),
        )

        brain_ctx = gbrain.format_context(brain_pages, brain_facts) or "None"
        system = _SYSTEM_PROMPT.format(
            date=date_str,
            context=relevant_ctx or "None",
            brain_context=brain_ctx,
        )

        messages = self._build_messages(conversation_history, user_message)
        response_text = await self._run_tool_loop(messages, system)

        # Persist exchange to vector memory + GBrain hot memory (fire-and-forget)
        msg_key = f"{telegram_id}_{date_str}_{len(messages)}"
        session_id = f"tg-{telegram_id}"
        await asyncio.gather(
            context_retriever.store_message(telegram_id, "user", user_message, f"u_{msg_key}"),
            context_retriever.store_message(telegram_id, "assistant", response_text, f"a_{msg_key}"),
            gbrain.extract_facts(
                f"User: {user_message}\n\nAssistant: {response_text}",
                session_id=session_id,
            ),
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
                        result = await _call_tool_with_retry(block.name, block.input)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(result, default=str),
                            }
                        )
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                return self._extract_text(response)

        return "I had trouble completing that request. Please try again."

    def _extract_text(self, response) -> str:
        parts = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(parts).strip() or "Done."


claude_client = ClaudeClient()
