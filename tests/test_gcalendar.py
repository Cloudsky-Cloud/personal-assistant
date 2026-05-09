import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_cal_service():
    svc = MagicMock()
    events_res = MagicMock()
    events_res.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "evt1",
                "summary": "Team standup",
                "start": {"dateTime": "2026-05-08T09:00:00Z"},
                "end": {"dateTime": "2026-05-08T09:30:00Z"},
                "description": "",
                "location": "",
                "attendees": [],
            }
        ]
    }
    events_res.insert.return_value.execute.return_value = {
        "id": "evt2",
        "summary": "New event",
    }
    svc.events.return_value = events_res
    return svc


def test_list_events(mock_cal_service):
    with patch("src.integrations.gcalendar.build_google_service", return_value=mock_cal_service):
        from src.integrations.gcalendar import GoogleCalendar
        cal = GoogleCalendar()
        events = cal.list_events(days=1)
        assert len(events) == 1
        assert events[0]["summary"] == "Team standup"
        assert events[0]["start"] == "2026-05-08T09:00:00Z"


def test_create_event(mock_cal_service):
    with patch("src.integrations.gcalendar.build_google_service", return_value=mock_cal_service):
        from src.integrations.gcalendar import GoogleCalendar
        cal = GoogleCalendar()
        result = cal.create_event(
            "New event",
            "2026-05-09T10:00:00Z",
            "2026-05-09T11:00:00Z",
        )
        assert result["id"] == "evt2"


def test_search_events(mock_cal_service):
    with patch("src.integrations.gcalendar.build_google_service", return_value=mock_cal_service):
        from src.integrations.gcalendar import GoogleCalendar
        cal = GoogleCalendar()
        results = cal.search_events("standup")
        assert len(results) == 1
