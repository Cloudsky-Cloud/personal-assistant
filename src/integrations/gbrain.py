"""GBrain HTTP client.

Communicates with a GBrain instance running in --http mode via JSON-RPC 2.0.
All methods degrade gracefully to empty results when GBrain is unconfigured
or unreachable, so the bot continues working without it.
"""
import json
import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class GBrainClient:
    def __init__(self):
        self._rpc_id = 0

    def enabled(self) -> bool:
        return bool(settings.gbrain_url and settings.gbrain_token)

    async def _call(self, tool_name: str, arguments: dict) -> Any:
        self._rpc_id += 1
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.gbrain_url.rstrip('/')}/mcp",
                headers={"Authorization": f"Bearer {settings.gbrain_token}"},
                json={
                    "jsonrpc": "2.0",
                    "id": self._rpc_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if "error" in data:
            raise RuntimeError(f"GBrain RPC error: {data['error']}")

        # MCP wraps tool results as content[0].text (JSON-encoded string)
        result = data.get("result", {})
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            try:
                return json.loads(content[0]["text"])
            except (json.JSONDecodeError, KeyError):
                return content[0].get("text", "")
        return result

    # ── Public API ────────────────────────────────────────────────────────────

    async def query(self, text: str, limit: int = 5) -> list[dict]:
        """Hybrid semantic + keyword search over brain pages."""
        if not self.enabled():
            return []
        try:
            result = await self._call("query", {"query": text, "limit": limit, "recency": "on"})
            pages = result.get("pages") or result if isinstance(result, list) else []
            return pages[:limit]
        except Exception as exc:
            logger.warning("GBrain query failed: %s", exc)
            return []

    async def recall(self, text: str, limit: int = 10) -> list[dict]:
        """Retrieve hot-memory facts semantically relevant to the query."""
        if not self.enabled():
            return []
        try:
            result = await self._call("recall", {"query": text, "limit": limit})
            facts = result.get("facts") or result if isinstance(result, list) else []
            return facts[:limit]
        except Exception as exc:
            logger.warning("GBrain recall failed: %s", exc)
            return []

    async def extract_facts(self, turn_text: str, session_id: str | None = None) -> None:
        """Extract and index facts from a conversation exchange into hot memory."""
        if not self.enabled():
            return
        try:
            args: dict = {"turn_text": turn_text[:8000]}  # cap to avoid body limit
            if session_id:
                args["session_id"] = session_id
            await self._call("extract_facts", args)
            logger.debug("GBrain extract_facts OK (session=%s)", session_id)
        except Exception as exc:
            logger.warning("GBrain extract_facts failed: %s", exc)

    async def put_page(self, slug: str, content: str) -> dict | None:
        """Write or update a brain page."""
        if not self.enabled():
            return None
        try:
            result = await self._call("put_page", {"slug": slug, "content": content})
            logger.info("GBrain put_page OK: %s", slug)
            return result
        except Exception as exc:
            logger.warning("GBrain put_page(%r) failed: %s", slug, exc)
            return None

    async def get_page(self, slug: str, fuzzy: bool = False) -> dict | None:
        """Retrieve a brain page by slug."""
        if not self.enabled():
            return None
        try:
            return await self._call("get_page", {"slug": slug, "fuzzy": fuzzy})
        except Exception as exc:
            logger.warning("GBrain get_page(%r) failed: %s", slug, exc)
            return None

    async def search(self, text: str, limit: int = 10) -> list[dict]:
        """Keyword-only search."""
        if not self.enabled():
            return []
        try:
            result = await self._call("search", {"query": text, "limit": limit})
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("GBrain search failed: %s", exc)
            return []

    async def is_available(self) -> bool:
        """Probe the /health endpoint."""
        if not self.enabled():
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{settings.gbrain_url.rstrip('/')}/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ── Formatting helpers (used by claude_client.py) ─────────────────────────

    def format_context(self, pages: list[dict], facts: list[dict]) -> str:
        """Format GBrain results as a readable context block for the system prompt."""
        parts: list[str] = []
        if facts:
            parts.append("Known facts from brain:")
            for f in facts[:6]:
                text = (
                    f.get("text") or f.get("content") or
                    f.get("statement") or str(f)
                )[:200]
                parts.append(f"  - {text}")
        if pages:
            parts.append("Relevant pages in brain:")
            for p in pages[:3]:
                title = p.get("title") or p.get("slug") or "Untitled"
                snippet = (p.get("content") or p.get("snippet") or "")[:300].strip()
                slug = p.get("slug", "")
                line = f"  - [{slug}] {title}"
                if snippet:
                    line += f": {snippet}"
                parts.append(line)
        return "\n".join(parts)


gbrain = GBrainClient()


# ── Contact ↔ brain-page helpers ─────────────────────────────────────────────

def contact_slug(name: str) -> str:
    """'Ahmed Ali' → 'people/ahmed-ali'"""
    import re
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return f"people/{slug}"


def contact_to_page(contact: dict) -> str:
    """Format a contact dict as a GBrain markdown page with YAML frontmatter."""
    name    = contact.get("name", "")
    email   = contact.get("email", "")
    company = contact.get("company") or ""
    mobile  = contact.get("phone_mobile") or ""
    work    = contact.get("phone_work") or ""
    home    = contact.get("phone_home") or ""
    street  = contact.get("address_street") or ""
    city    = contact.get("address_city") or ""
    country = contact.get("address_country") or ""
    notes   = contact.get("notes") or ""
    bday    = contact.get("birthday") or ""

    # YAML frontmatter
    fm_lines = [
        "---",
        f"name: {name}",
        f"email: {email}",
    ]
    if company:
        fm_lines.append(f"company: {company}")
    fm_lines.append("tags: [contact, person]")
    fm_lines.append("---")

    # Body
    lines = [f"# {name}", ""]
    rows: list[tuple[str, str]] = []
    if email:   rows.append(("Email", email))
    if mobile:  rows.append(("Mobile", mobile))
    if work:    rows.append(("Work phone", work))
    if home:    rows.append(("Home phone", home))
    if company: rows.append(("Company", company))
    location = ", ".join(p for p in [city, country] if p)
    if location: rows.append(("Location", location))
    if street:  rows.append(("Address", street))
    if bday:    rows.append(("Birthday", bday))

    if rows:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        for field, value in rows:
            lines.append(f"| {field} | {value} |")
        lines.append("")

    if notes:
        lines.append("## Notes")
        lines.append(notes)

    return "\n".join(fm_lines) + "\n\n" + "\n".join(lines)
