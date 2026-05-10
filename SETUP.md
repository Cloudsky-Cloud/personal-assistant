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
| Fitness API (Galaxy Watch — fallback) | https://console.cloud.google.com/apis/library/fitness.googleapis.com |
| Google Health Connect API (Galaxy Watch — primary) | https://console.cloud.google.com/apis/library/health.googleapis.com |

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

---

## GBrain (optional long-term memory)

GBrain gives the bot a persistent, searchable knowledge base. Without it everything still works — GBrain is purely additive.

### Step A — Install on the VPS

```bash
# Install Bun (GBrain requires Bun ≥1.3.10, not Node.js)
curl -fsSL https://bun.sh/install | bash
source ~/.bashrc

# Clone and link
git clone https://github.com/garrytan/gbrain /opt/gbrain
cd /opt/gbrain
bun install
bun link          # makes 'gbrain' available system-wide
```

### Step B — Start GBrain as a service

```bash
# Start the HTTP server (runs on port 3131)
gbrain serve --http --port 3131 --public-url http://localhost:3131 &

# Or create a systemd unit so it survives reboots:
cat > /etc/systemd/system/gbrain.service << 'EOF'
[Unit]
Description=GBrain memory server
After=network.target

[Service]
ExecStart=/root/.bun/bin/gbrain serve --http --port 3131 --public-url http://localhost:3131
Restart=always
WorkingDirectory=/opt/gbrain
Environment=GBRAIN_HOME=/opt/gbrain-data

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now gbrain
```

### Step C — Create a bot token

```bash
gbrain auth create "personal-assistant-bot"
# → prints a bearer token — copy it
```

### Step D — Update `.env`

```
GBRAIN_URL=http://localhost:3131
GBRAIN_TOKEN=<paste token from Step C>
```

Restart the bot: `docker-compose restart bot`

### What GBrain enables

| Feature | How it works |
|---|---|
| Auto-read before every reply | Bot fetches relevant pages + hot-memory facts before calling Claude |
| Auto-write after every reply | `extract_facts` indexes contacts, decisions, tasks from each exchange |
| `brain_search` tool | Say "what do you know about Ahmed?" — searches pages + facts |
| `brain_write` tool | Say "remember that..." — stores permanently in hot memory; add a slug to create a full page |
| Nightly dream cycle (2 AM) | Consolidates the day's conversations into a structured daily log page |

### Deployment note

When deploying via `vps_deploy` (git pull + docker build), GBrain continues running as a separate systemd service — no downtime.

---

## Troubleshooting

### Galaxy Watch shows "No data" in the morning briefing

The bot tries Health Connect first, then falls back to Google Fit.

**Health Connect path (primary):**
1. Enable the Google Health Connect API: https://console.cloud.google.com/apis/library/health.googleapis.com
2. Make sure your Galaxy Watch syncs to the **Health Connect** app on your phone (Samsung Health → Settings → Connected services → Health Connect).
3. Re-authorize to pick up the new `googlehealth.*` scopes — delete `data/google_token.json` and re-run Step 4.
4. During authorization Google will show a warning screen ("unverified app") for the sensitive `googlehealth.*` scopes — click **Continue** to proceed.

**Google Fit fallback path:**
1. Enable the Fitness API: https://console.cloud.google.com/apis/library/fitness.googleapis.com
2. Make sure your Galaxy Watch syncs to Google Fit on your phone (open the Google Fit app and confirm data is visible there).

### "Google token is missing required scopes"
Delete `data/google_token.json` and re-run Step 4.

### "Google [API] is not enabled"
Enable the API using the link in the warning, wait 1 minute, then restart the bot.

### "Google credentials file not found"
Make sure `credentials/google_credentials.json` exists (Step 2).

### Bot starts but Google features don't work
Check the startup logs for any `WARNING` lines about disabled APIs.
