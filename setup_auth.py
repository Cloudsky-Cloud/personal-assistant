#!/usr/bin/env python3
"""One-time Google OAuth2 authorization.

Run with:
    docker-compose run --rm bot python setup_auth.py
or locally:
    python setup_auth.py

Prints an authorization URL to open in your browser, then prompts for
the code. Saves the token to data/google_token.json (persisted across
container restarts via the volume).
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/contacts",
]


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
    print("You can now start the bot with: docker-compose up -d")


if __name__ == "__main__":
    main()
