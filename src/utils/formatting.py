import re


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(r"([" + re.escape(special) + r"])", r"\\\1", str(text))


def format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "No pending tasks."
    quad_emoji = {
        "do_now": "🔴",
        "schedule": "🟡",
        "delegate": "🔵",
        "eliminate": "⚪",
    }
    lines = ["*Your prioritized tasks:*\n"]
    for i, t in enumerate(tasks, 1):
        emoji = quad_emoji.get(t.get("quadrant", ""), "⚪")
        due_str = f" _(due: {t['due_date']})_" if t.get("due_date") else ""
        title = escape_md(t.get("title", ""))
        lines.append(f"{i}\\. {emoji} {title}{due_str}")
    return "\n".join(lines)


def format_email_summary(emails: list[dict]) -> str:
    if not emails:
        return "No unread emails."
    lines = ["*Unread emails:*\n"]
    for e in emails[:5]:
        subject = escape_md(e.get("subject", "No subject"))
        sender = escape_md(e.get("from", "Unknown"))
        lines.append(f"• *{subject}*\n  From: {sender}")
    if len(emails) > 5:
        lines.append(f"_…and {len(emails) - 5} more_")
    return "\n".join(lines)


def format_calendar_events(events: list[dict]) -> str:
    if not events:
        return "No upcoming events."
    lines = ["*Upcoming events:*\n"]
    for e in events[:8]:
        title = escape_md(e.get("summary", "No title"))
        start = escape_md(str(e.get("start", "")))
        lines.append(f"📅 *{title}*\n  {start}")
    return "\n".join(lines)


def truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n\n_\\[truncated\\]_"
