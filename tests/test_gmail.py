import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_gmail_service():
    svc = MagicMock()
    messages_res = MagicMock()
    messages_res.list.return_value.execute.return_value = {
        "messages": [{"id": "msg1", "threadId": "t1"}]
    }
    messages_res.get.return_value.execute.return_value = {
        "id": "msg1",
        "snippet": "Hello from test",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Test Subject"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "Date", "value": "Thu, 1 Jan 2026 10:00:00 +0000"},
            ],
            "body": {"data": "SGVsbG8gV29ybGQ="},  # base64("Hello World")
        },
        "labelIds": ["INBOX", "UNREAD"],
    }
    messages_res.modify.return_value.execute.return_value = {}
    svc.users.return_value.messages.return_value = messages_res
    labels_res = MagicMock()
    labels_res.list.return_value.execute.return_value = {"labels": []}
    svc.users.return_value.labels.return_value = labels_res
    return svc


def test_list_unread(mock_gmail_service):
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        emails = g.list_unread(max_results=5)
        assert len(emails) == 1
        assert emails[0]["subject"] == "Test Subject"
        assert emails[0]["from"] == "sender@example.com"
        assert "Hello World" in emails[0]["body"]


def test_search_emails(mock_gmail_service):
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        results = g.search("from:sender@example.com")
        assert len(results) == 1


def test_mark_read_calls_modify(mock_gmail_service):
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        g.mark_read("msg1")
        modify = mock_gmail_service.users.return_value.messages.return_value.modify
        modify.assert_called_once_with(
            userId="me",
            id="msg1",
            body={"removeLabelIds": ["UNREAD"]},
        )


def test_send_email(mock_gmail_service):
    mock_gmail_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent123"
    }
    with patch("src.integrations.gmail.build_google_service", return_value=mock_gmail_service):
        from src.integrations.gmail import Gmail
        g = Gmail()
        result = g.send_email(
            to="recipient@example.com",
            subject="Hello",
            body="This is a test email.",
        )
        assert result["id"] == "sent123"
        assert result["to"] == "recipient@example.com"
        assert result["subject"] == "Hello"
        send = mock_gmail_service.users.return_value.messages.return_value.send
        send.assert_called_once()
        call_kwargs = send.call_args.kwargs
        assert call_kwargs["userId"] == "me"
        assert "raw" in call_kwargs["body"]
