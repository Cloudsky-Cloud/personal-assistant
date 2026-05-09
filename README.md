# Personal Assistant Bot

A production-grade personal assistant Telegram bot powered by Claude claude-sonnet-4-6.

## Features

- 📧 **Email** — Read, summarize, and search Gmail; take action on emails
- 📅 **Calendar** — List events, create reminders, proactive alerts before meetings
- 📂 **Drive** — Search and list Google Drive files
- ✅ **Tasks** — Create, prioritize, and complete Google Tasks
- 🌅 **Daily Briefing** — Automated morning summary of emails, calendar, and top tasks
- 🎙️ **Voice Notes** — Send voice messages; they're transcribed and processed as commands
- 🧠 **Memory** — SQLite + ChromaDB vector search remembers your preferences and past context
- 🤖 **Claude-powered** — Full conversation with tool use; just describe what you need

---

## Setup

### Prerequisites

- Docker + Docker Compose
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Anthropic API key from [console.anthropic.com](https://console.anthropic.com)
- Google Cloud project with OAuth2 credentials

### 1. Copy and configure environment

```bash
cp .env.template .env
# Edit .env — fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, TELEGRAM_ALLOWED_USERS
```

### 2. Set up Google credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project (or use existing)
3. Enable these APIs: **Gmail API**, **Google Calendar API**, **Google Drive API**, **Google Tasks API**
4. Create OAuth 2.0 credentials → **Desktop app** type
5. Download the JSON file and save it as `credentials/google_credentials.json`

### 3. Authorize Google APIs (one-time)

```bash
docker-compose run --rm bot python setup_auth.py
```

This opens a browser for OAuth consent. The token is saved to `data/google_token.json` (persisted across restarts).

### 4. Start the bot

```bash
docker-compose up -d
docker-compose logs -f   # watch logs
```

### 5. Open Telegram and send `/start`

Your Telegram user ID must be in `TELEGRAM_ALLOWED_USERS` in your `.env`.  
Find your ID by messaging [@userinfobot](https://t.me/userinfobot).

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/briefing` | Trigger daily briefing immediately |
| `/tasks` | Show prioritized task list |
| `/help` | Show all commands |

Or send any text or voice message — the bot handles it via Claude.

## Examples

```
"Summarize my unread emails from today"
"Schedule a dentist appointment for Friday at 10am"
"What's on my calendar this week?"
"Create a task: prepare Q2 report, due Thursday"
"Find the project proposal in my Drive"
```

Or record a voice note — it's transcribed automatically.

---

## Architecture

```
Telegram → python-telegram-bot → Claude (anthropic SDK)
                                      ↓  tool use
                              Gmail / Calendar / Drive / Tasks
                                      ↓
                        SQLite (history) + ChromaDB (vector memory)
                                      ↓
                              APScheduler (briefings + reminders)
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
