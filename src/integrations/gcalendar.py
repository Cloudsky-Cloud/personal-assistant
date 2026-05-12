from datetime import datetime, timezone, timedelta
from typing import Optional
from .google_auth import build_google_service


class GoogleCalendar:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("calendar", "v3")
        return self._service

    def list_events(
        self,
        days: int = 7,
        calendar_id: str = "primary",
        time_min: Optional[datetime] = None,
    ) -> list[dict]:
        if time_min is None:
            time_min = datetime.now(timezone.utc)
        time_max = time_min + timedelta(days=days)
        res = self._svc().events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "No title"),
                "start": (
                    e.get("start", {}).get("dateTime")
                    or e.get("start", {}).get("date", "")
                ),
                "end": (
                    e.get("end", {}).get("dateTime")
                    or e.get("end", {}).get("date", "")
                ),
                "description": e.get("description", ""),
                "location": e.get("location", ""),
                "attendees": [a.get("email") for a in e.get("attendees", [])],
                # True when the API returned a date (not dateTime) — i.e. an all-day event
                "is_all_day": "dateTime" not in e.get("start", {}),
                # "default", "focusTime", "outOfOffice", "workingLocation", "fromGmail"
                "event_type": e.get("eventType", "default"),
            }
            for e in res.get("items", [])
        ]

    def create_event(
        self,
        title: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        attendees: Optional[list[str]] = None,
        calendar_id: str = "primary",
    ) -> dict:
        body: dict = {
            "summary": title,
            "description": description,
            "location": location,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end": {"dateTime": end, "timeZone": "UTC"},
        }
        if attendees:
            body["attendees"] = [{"email": e} for e in attendees]
        return self._svc().events().insert(
            calendarId=calendar_id, body=body
        ).execute()

    def search_events(self, query: str, days: int = 30) -> list[dict]:
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=days)
        res = self._svc().events().list(
            calendarId="primary",
            q=query,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary", "No title"),
                "start": (
                    e.get("start", {}).get("dateTime")
                    or e.get("start", {}).get("date", "")
                ),
            }
            for e in res.get("items", [])
        ]

    def delete_event(self, event_id: str, calendar_id: str = "primary"):
        self._svc().events().delete(
            calendarId=calendar_id, eventId=event_id
        ).execute()


gcalendar = GoogleCalendar()
