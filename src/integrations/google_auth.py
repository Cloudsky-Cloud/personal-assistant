from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import settings

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts",
]


def get_credentials() -> Credentials:
    token_path = Path(settings.google_token_file)
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds

    if not creds or not creds.valid:
        raise RuntimeError(
            "Google credentials not found or invalid. "
            "Run: docker-compose run --rm bot python setup_auth.py"
        )
    return creds


def build_google_service(api_name: str, api_version: str):
    creds = get_credentials()
    return build(api_name, api_version, credentials=creds)
