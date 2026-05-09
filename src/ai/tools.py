from typing import Any

from ..integrations.gmail import gmail
from ..integrations.gcalendar import gcalendar
from ..integrations.gdrive import gdrive
from ..integrations.gtasks import gtasks
from ..tasks.prioritizer import prioritizer
from ..memory.contacts import contacts_db
from ..memory.projects import projects_db

# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "gmail_list_unread",
        "description": (
            "List unread emails from Gmail. "
            "Returns subject, sender, date, and snippet for each email."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of emails to return",
                }
            },
        },
    },
    {
        "name": "gmail_search",
        "description": (
            "Search Gmail emails using query string. "
            "Supports Gmail operators: from:, to:, subject:, after:, before:, has:attachment, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query e.g. 'from:boss@company.com subject:invoice'",
                },
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_mark_read",
        "description": "Mark an email as read by its message ID.",
        "input_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    {
        "name": "calendar_list_events",
        "description": "List upcoming Google Calendar events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "default": 7,
                    "description": "Number of days ahead to fetch events for",
                }
            },
        },
    },
    {
        "name": "calendar_create_event",
        "description": (
            "Create a new Google Calendar event. "
            "start and end must be ISO 8601 datetime strings in UTC, "
            "e.g. '2026-05-10T14:00:00Z'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {
                    "type": "string",
                    "description": "ISO 8601 UTC datetime e.g. 2026-05-10T14:00:00Z",
                },
                "end": {
                    "type": "string",
                    "description": "ISO 8601 UTC datetime",
                },
                "description": {"type": "string", "default": ""},
                "location": {"type": "string", "default": ""},
                "attendees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of attendee email addresses",
                },
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "calendar_search_events",
        "description": "Search for Google Calendar events by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "days": {"type": "integer", "default": 30},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_search",
        "description": (
            "Search Google Drive files. "
            "Supports Drive query syntax: name contains 'report', "
            "mimeType='application/pdf', modifiedTime > '2026-01-01T00:00:00'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Drive search query",
                },
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_list_recent",
        "description": "List the most recently modified Google Drive files.",
        "input_schema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer", "default": 10}},
        },
    },
    {
        "name": "tasks_list",
        "description": "List pending tasks from Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"max_results": {"type": "integer", "default": 20}},
        },
    },
    {
        "name": "tasks_create",
        "description": "Create a new task in Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "notes": {"type": "string", "default": ""},
                "due": {
                    "type": "string",
                    "description": "RFC 3339 datetime e.g. 2026-05-10T00:00:00Z (optional)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "tasks_complete",
        "description": "Mark a Google Task as completed by its task ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "gmail_send_email",
        "description": (
            "Compose and send an email via Gmail. "
            "Use this when the user asks to send, write, or email someone. "
            "You have full permission to send emails on the user's behalf."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Full email body (plain text)"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "contacts_lookup",
        "description": (
            "Look up contacts by name from the local contacts database. "
            "Returns all matches (up to 10). "
            "Use this when the user refers to a recipient by name rather than email address. "
            "If multiple matches are returned, ask the user to clarify which one they mean."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact name (or partial name) to search for"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "contacts_upsert",
        "description": (
            "Save or update a contact (name and email) in the local contacts database. "
            "Use this when the user adds or updates a contact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
            "required": ["name", "email"],
        },
    },
    {
        "name": "contacts_list",
        "description": "List all contacts stored in the local contacts database.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "contacts_delete",
        "description": "Delete a contact by name from the local contacts database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the contact to delete"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "projects_create",
        "description": (
            "Create a new project in the local projects database. "
            "Use when the user says 'add project', 'create project', or similar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "complete", "archived"],
                    "description": "Initial status (default: active)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date as ISO 8601 date e.g. 2026-05-16 (optional)",
                },
                "description": {"type": "string", "description": "Project description (optional)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "projects_update",
        "description": (
            "Update a project's fields. "
            "Use for 'mark X done', 'update X status to complete', 'rename X', etc. "
            "project_name is a partial or full match against the stored name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Name (or partial name) of the project to update"},
                "new_name": {"type": "string", "description": "Rename the project to this value"},
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "complete", "archived"],
                },
                "due_date": {"type": "string", "description": "New due date as ISO 8601 e.g. 2026-05-16"},
                "description": {"type": "string"},
            },
            "required": ["project_name"],
        },
    },
    {
        "name": "projects_list",
        "description": (
            "List projects from the local projects database. "
            "Optionally filter by status or by due date. "
            "For 'what's due this week' pass due_before as the end of the current week (ISO date). "
            "Returns name, status, due_date, description, and note count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "paused", "complete", "archived"],
                    "description": "Filter by status (omit for all projects)",
                },
                "due_before": {
                    "type": "string",
                    "description": "Return only projects with due_date on or before this ISO date",
                },
            },
        },
    },
    {
        "name": "projects_delete",
        "description": "Delete a project (and all its notes) by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name (or partial name) of the project to delete"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "projects_add_note",
        "description": (
            "Add a note to an existing project. "
            "Use when the user says 'add note to X', 'note for X: ...', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Name (or partial name) of the project"},
                "content": {"type": "string", "description": "Note content"},
            },
            "required": ["project_name", "content"],
        },
    },
    {
        "name": "projects_get_notes",
        "description": "Get all notes for a project, along with the project's details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Name (or partial name) of the project"},
            },
            "required": ["project_name"],
        },
    },
    {
        "name": "projects_search",
        "description": (
            "Search projects by keyword across name, description, and note content. "
            "Use for 'find projects about X' or 'show projects mentioning Y'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "prioritize_tasks",
        "description": (
            "Score and rank a list of tasks by urgency and importance using the Eisenhower matrix. "
            "Returns tasks sorted by priority with quadrant labels: "
            "do_now, schedule, delegate, or eliminate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string", "default": ""},
                            "due_in_hours": {
                                "type": "number",
                                "description": "Hours until due date (optional)",
                            },
                        },
                        "required": ["title"],
                    },
                }
            },
            "required": ["tasks"],
        },
    },
]


# ── Dispatcher ───────────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> Any:
    """Execute a named tool and return a JSON-serializable result."""
    match tool_name:
        case "gmail_list_unread":
            return gmail.list_unread(tool_input.get("max_results", 10))

        case "gmail_search":
            return gmail.search(
                tool_input["query"], tool_input.get("max_results", 10)
            )

        case "gmail_mark_read":
            gmail.mark_read(tool_input["message_id"])
            return {"status": "marked_read"}

        case "calendar_list_events":
            return gcalendar.list_events(tool_input.get("days", 7))

        case "calendar_create_event":
            return gcalendar.create_event(
                title=tool_input["title"],
                start=tool_input["start"],
                end=tool_input["end"],
                description=tool_input.get("description", ""),
                location=tool_input.get("location", ""),
                attendees=tool_input.get("attendees"),
            )

        case "calendar_search_events":
            return gcalendar.search_events(
                tool_input["query"], tool_input.get("days", 30)
            )

        case "drive_search":
            return gdrive.search(
                tool_input["query"], tool_input.get("max_results", 10)
            )

        case "drive_list_recent":
            return gdrive.list_recent(tool_input.get("max_results", 10))

        case "tasks_list":
            return gtasks.list_tasks(tool_input.get("max_results", 20))

        case "tasks_create":
            return gtasks.create_task(
                title=tool_input["title"],
                notes=tool_input.get("notes", ""),
                due=tool_input.get("due"),
            )

        case "tasks_complete":
            return gtasks.complete_task(tool_input["task_id"])

        case "gmail_send_email":
            return gmail.send_email(
                to=tool_input["to"],
                subject=tool_input["subject"],
                body=tool_input["body"],
            )

        case "contacts_lookup":
            results = contacts_db.lookup(tool_input["name"])
            if not results:
                return {"error": f"No contact found for '{tool_input['name']}'"}
            return {"contacts": results}

        case "contacts_upsert":
            contacts_db.upsert(tool_input["name"], tool_input["email"])
            return {"status": "saved", "name": tool_input["name"], "email": tool_input["email"]}

        case "contacts_list":
            contacts = contacts_db.list_all()
            return {"contacts": contacts, "count": len(contacts)}

        case "contacts_delete":
            deleted = contacts_db.delete(tool_input["name"])
            if deleted == 0:
                return {"error": f"No contact found matching '{tool_input['name']}'"}
            return {"status": "deleted", "count": deleted}

        case "projects_create":
            return projects_db.create(
                name=tool_input["name"],
                status=tool_input.get("status", "active"),
                due_date=tool_input.get("due_date"),
                description=tool_input.get("description", ""),
            )

        case "projects_update":
            return projects_db.update(
                tool_input["project_name"],
                name=tool_input.get("new_name"),
                status=tool_input.get("status"),
                due_date=tool_input.get("due_date"),
                description=tool_input.get("description"),
            )

        case "projects_list":
            return projects_db.list_projects(
                status=tool_input.get("status"),
                due_before=tool_input.get("due_before"),
            )

        case "projects_delete":
            deleted = projects_db.delete(tool_input["name"])
            if deleted == 0:
                return {"error": f"No project found matching '{tool_input['name']}'"}
            return {"status": "deleted", "count": deleted}

        case "projects_add_note":
            return projects_db.add_note(
                project_name=tool_input["project_name"],
                content=tool_input["content"],
            )

        case "projects_get_notes":
            return projects_db.get_notes(tool_input["project_name"])

        case "projects_search":
            return projects_db.search(tool_input["query"])

        case "prioritize_tasks":
            scored = prioritizer.score_list(tool_input["tasks"])
            return [
                {
                    **{k: v for k, v in t.items() if k != "score"},
                    "urgency": t["score"].urgency,
                    "importance": t["score"].importance,
                    "priority": t["score"].priority,
                    "quadrant": t["score"].quadrant,
                }
                for t in scored
            ]

        case _:
            return {"error": f"Unknown tool: {tool_name}"}
