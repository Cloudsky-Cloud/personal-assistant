#!/usr/bin/env python3
"""One-time Google OAuth2 authorization.

Run with:
    docker-compose run --rm bot python setup_auth.py
or locally:
    python setup_auth.py

Prints an authorization URL to open in your browser, then prompts for
the code. Saves the token to data/google_token.json (persisted across
container restarts via the volume).

After authorization, verifies that each required Google API is enabled
and prints a direct link for any that are not.
"""
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent))
from src.integrations.google_scopes import SCOPES  # noqa: E402

_API_ENABLE_LINKS = {
    "Gmail":             "https://console.cloud.google.com/apis/library/gmail.googleapis.com",
    "Calendar":          "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com",
    "Drive":             "https://console.cloud.google.com/apis/library/drive.googleapis.com",
    "Tasks":             "https://console.cloud.google.com/apis/library/tasks.googleapis.com",
    "People (Contacts)": "https://console.cloud.google.com/apis/library/people.googleapis.com",
}

_API_PROBES = [
    ("Gmail",             "gmail",    "v1", lambda svc: svc.users().getProfile(userId="me").execute()),
    ("Calendar",          "calendar", "v3", lambda svc: svc.calendarList().list(maxResults=1).execute()),
    ("Drive",             "drive",    "v3", lambda svc: svc.files().list(pageSize=1, fields="files(id)").execute()),
    ("Tasks",             "tasks",    "v1", lambda svc: svc.tasklists().list(maxResults=1).execute()),
    ("People (Contacts)", "people",   "v1", lambda svc: svc.people().get(resourceName="people/me", personFields="names").execute()),
]


def _verify_apis(creds) -> None:
    print("\nVerifying that all required Google APIs are enabled...\n")
    all_ok = True
    for name, api_name, api_version, probe in _API_PROBES:
        try:
            svc = build(api_name, api_version, credentials=creds)
            probe(svc)
            print(f"  OK  {name}")
        except Exception as exc:
            msg = str(exc)
            if any(kw in msg for kw in ("has not been used", "disabled", "ACCESS_DISABLED")):
                link = _API_ENABLE_LINKS.get(name, "https://console.cloud.google.com/apis")
                print(f"  DISABLED  {name}")
                print(f"            Enable it at: {link}")
                all_ok = False
            else:
                print(f"  WARN  {name}: {exc}")

    if all_ok:
        print("\nAll APIs are enabled. You're ready to start the bot.")
    else:
        print(
            "\nSome APIs are disabled. Enable them using the links above,"
            "\nthen wait ~1 minute before starting the bot."
        )


def main():
    credentials_file = Path("credentials/google_credentials.json")
    token_file = Path("data/google_token.json")
    token_file.parent.mkdir(parents=True, exist_ok=True)

    if not credentials_file.exists():
        print(f"ERROR: {credentials_file} not found.")
        print(
            "Download OAuth2 credentials from Google Cloud Console "
            "(Desktop app type) and save as credentials/google_credentials.json"
        )
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")

    print("\nOpen this URL in your browser:\n")
    print(auth_url)
    print()
    code = input("Paste the authorization code here: ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials
    token_file.write_text(creds.to_json())
    print(f"\nAuthorization successful. Token saved to {token_file}")

    _verify_apis(creds)


if __name__ == "__main__":
    main()
