# Setup Guide

## Prerequisites

- Docker and Docker Compose
- A Google account
- A Telegram account

---

## Step 1 — Enable Google Cloud APIs

Go to [Google Cloud Console](https://console.cloud.google.com/) and enable **all five APIs** for your project. The bot will not work if any are missing.

| API | Enable Link |
|-----|-------------|
| Gmail API | https://console.cloud.google.com/apis/library/gmail.googleapis.com |
| Google Calendar API | https://console.cloud.google.com/apis/library/calendar-json.googleapis.com |
| Google Drive API | https://console.cloud.google.com/apis/library/drive.googleapis.com |
| Google Tasks API | https://console.cloud.google.com/apis/library/tasks.googleapis.com |
| People API (Contacts) | https://console.cloud.google.com/apis/library/people.googleapis.com |
| Cloud Text-to-Speech API | https://console.cloud.google.com/apis/library/texttospeech.googleapis.com |

After enabling, wait about **1 minute** before continuing.

---

## Step 2 — Create OAuth2 Credentials

1. In Google Cloud Console, go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Download the JSON file
5. Save it as `credentials/google_credentials.json` in this project

---

## Step 3 — Configure Environment

Copy the template and fill in your values:

```bash
cp .env.template .env
```

Required values in `.env`:

```
TELEGRAM_BOT_TOKEN=      # From @BotFather on Telegram
ANTHROPIC_API_KEY=       # From console.anthropic.com
```

---

## Step 4 — Authorize Google Account

Run the one-time OAuth flow. This saves a token to `data/google_token.json` and
verifies that all required APIs are enabled:

```bash
docker-compose run --rm bot python setup_auth.py
```

The script will:
1. Print an authorization URL — open it in your browser
2. Ask you to paste the authorization code
3. Save the token
4. Check each API and print a warning with an enable link for any that are disabled

---

## Step 5 — Start the Bot

```bash
docker-compose up -d
```

On startup the bot will:
- Validate that env vars and Google token are present (exits with error if not)
- Probe each Google API and log a WARNING for any that are disabled (does not crash)

Check logs with:

```bash
docker-compose logs -f
```

---

## Troubleshooting

### "Google token is missing required scopes"
Delete `data/google_token.json` and re-run Step 4.

### "Google [API] is not enabled"
Enable the API using the link in the warning, wait 1 minute, then restart the bot.

### "Google credentials file not found"
Make sure `credentials/google_credentials.json` exists (Step 2).

### Bot starts but Google features don't work
Check the startup logs for any `WARNING` lines about disabled APIs.
