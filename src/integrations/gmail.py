import base64
import email.mime.multipart
import email.mime.text
from typing import Optional
from .google_auth import build_google_service


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
    return ""


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


class Gmail:
    def __init__(self):
        self._service = None

    def _svc(self):
        if self._service is None:
            self._service = build_google_service("gmail", "v1")
        return self._service

    def _fetch_message(self, msg_id: str) -> dict:
        raw = self._svc().users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        headers = raw["payload"].get("headers", [])
        return {
            "id": raw["id"],
            "subject": _header(headers, "Subject"),
            "from": _header(headers, "From"),
            "date": _header(headers, "Date"),
            "snippet": raw.get("snippet", ""),
            "body": _decode_body(raw["payload"])[:2000],
            "labels": raw.get("labelIds", []),
        }

    def list_unread(self, max_results: int = 10) -> list[dict]:
        res = self._svc().users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        return [self._fetch_message(m["id"]) for m in res.get("messages", [])]

    def search(self, query: str, max_results: int = 10) -> list[dict]:
        res = self._svc().users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        return [self._fetch_message(m["id"]) for m in res.get("messages", [])]

    def mark_read(self, msg_id: str):
        self._svc().users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

    def label_message(self, msg_id: str, label_name: str):
        labels = self._svc().users().labels().list(userId="me").execute()
        label_id = next(
            (lb["id"] for lb in labels.get("labels", []) if lb["name"] == label_name),
            None,
        )
        if label_id:
            self._svc().users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()

    def send_email(self, to: str, subject: str, body: str) -> dict:
        msg = email.mime.multipart.MIMEMultipart()
        msg["to"] = to
        msg["subject"] = subject
        msg.attach(email.mime.text.MIMEText(body, "plain"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = self._svc().users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        return {"id": sent["id"], "to": to, "subject": subject}


gmail = Gmail()
