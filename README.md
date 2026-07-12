# AI Telegram Agent

An AI agent connected to a Telegram bot that automates schedule management and
provides AI-powered conversations.

## What it does

| Requirement | How it is covered |
|---|---|
| **Telegram bot integration** | `bot.py` runs a bot (long polling) that answers commands, chats, and pushes notifications on its own. |
| **Calendar integration** | `calendar_client.py` authenticates against the Khmer Calendar API (`https://api-calender-sigma.vercel.app/api/v1`) with the account from `.env` (bearer token, automatic re-login on expiry) and reads the day view: events, notes, public holidays, Buddhist events, work shift. |
| **Schedule summary** | `planner.build_summary()` produces a concise overview: events with times/locations, busy-hours total, holidays, Khmer lunar date, notes. |
| **Complete daily plan** | `planner.generate_plan()` asks the selected AI for a morning-to-night plan (work blocks, meals, breaks, free time) around the fixed calendar events. If no AI key is configured, a built-in deterministic planner produces the plan instead, so the digest always works. |
| **Automatic daily sending** | A scheduler inside the bot sends the digest (summary + plan) every day at the configured time (default **06:30**, `Asia/Phnom_Penh`) to every subscribed chat — no manual action needed. |
| **Multi-LLM integration** | `llm.py` talks to **Google Gemini**, **Anthropic Claude** (official SDK) and **OpenAI GPT**. |
| **Keys managed via Telegram** | `/setkey`, `/delkey`, `/keys`, `/model`, `/setmodel` — keys are stored in `config.json` (git-ignored); the bot deletes the message containing the raw key when it can. |
| **Chat with the selected AI** | Any plain text message is answered by the active provider in a natural, friendly tone, with per-chat conversation history (`/reset` clears it). The chat is **grounded in real data**: today's and tomorrow's calendar are injected into every request, so questions like *"am I free tomorrow afternoon?"* are answered from the actual schedule. |
| **Long-term memory** | The bot remembers lasting facts across restarts (`memory.py` → `memory.json`). Facts are saved automatically when you mention them in chat (the AI tags them with `[REMEMBER: ...]`), or explicitly via `/remember`. Manage with `/memory` and `/forget`. |
| **English / Khmer** | `/language en` or `/language km` per chat (`i18n.py`). Switches the interface (help, sign-in prompt, schedule summary, digest, confirmations), the built-in fallback plan, and instructs the AI to chat and plan in Khmer. |
| **Dynamic input per user** | **Sign-in is required**: every chat must connect its own Calendar API account (`/login` or `/register`) before using the bot — until then, all features answer with a sign-in prompt. After sign-in, events, notes, digest and AI answers use that personal calendar, and users add data straight from Telegram with `/addevent` and `/addnote`. `/account` shows who is signed in, `/logout` signs out. |

## Setup

1. **Create the bot** — in Telegram, open **@BotFather** → `/newbot` → choose a
   name and username → copy the token.
2. **Configure** — open `.env` and paste the token:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAF...your-token...
   ```
   The calendar credentials are already filled in.
3. **Install & run** (Windows):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   .venv\Scripts\python bot.py
   ```
   or simply double-click **run.bat**.
4. **In Telegram** — send `/start` to your bot, then **sign in** (required
   before anything else works):
   ```
   /login jengah6@gmail.com J@10hab!9        (existing account)
   /register me@example.com mypassword My Name   (or create a new one)
   ```
   The chat is now subscribed to the automatic daily digest of that account.
5. **(Optional) add an AI key** so plans and chat are AI-powered:
   ```
   /setkey gemini  AIza...        (from https://aistudio.google.com/apikey)
   /setkey claude  sk-ant-...     (from https://platform.claude.com)
   /setkey openai  sk-...         (from https://platform.openai.com)
   /model claude                  (choose the active provider)
   ```

## Commands

| Command | Description |
|---|---|
| `/start` | Subscribe this chat to the daily digest + show help |
| `/today [YYYY-MM-DD]` | Schedule summary **and** AI daily plan |
| `/tomorrow` | Summary + plan for tomorrow |
| `/yesterday` | Summary + plan for yesterday |
| `/summary [YYYY-MM-DD]` | Schedule summary only |
| `/plan [YYYY-MM-DD]` | Daily plan only |
| `/settime HH:MM` | Set the automatic digest time (24 h, Asia/Phnom_Penh) |
| `/stop` | Unsubscribe from the daily digest |
| `/addevent <date> <time> <title> [@ place]` | Add an event (`/addevent tomorrow 14:00-15:30 Meeting @ IT STEP`) |
| `/addnote [date] <text>` | Add a note (date defaults to today) |
| `/login <email> <password>` | Connect your own calendar account to this chat |
| `/register <email> <password> [name]` | Create a new calendar account and connect it |
| `/account` | Show which calendar account this chat uses |
| `/logout` | Disconnect the personal account (back to the shared one) |
| *(any text)* | Chat with the selected AI model (calendar-aware, friendly tone) |
| `/remember <fact>` | Save a fact to long-term memory |
| `/memory` | List everything the bot remembers |
| `/forget <n\|all>` | Forget one fact (by number) or everything |
| `/model [provider]` | Show or switch the active AI (gemini / claude / openai) |
| `/setkey <provider> <key>` | Save an API key (use a private chat!) |
| `/delkey <provider>` | Delete a stored key |
| `/keys` | List providers, masked keys, models |
| `/setmodel <provider> <model>` | Override the model id (defaults: `gemini-2.5-flash`, `claude-opus-4-8`, `gpt-4o-mini`) |
| `/reset` | Clear the AI conversation history |
| `/language <en\|km>` | Interface + AI language: English or ភាសាខ្មែរ |
| `/help` | Show help |

## Project layout

```
bot.py              Telegram bot: commands, AI chat, automatic daily digest
planner.py          Schedule summary + AI daily plan (with deterministic fallback)
llm.py              Multi-provider gateway: Gemini / Claude (SDK) / OpenAI
memory.py           Long-term per-chat memory persisted to memory.json
i18n.py             English/Khmer interface strings (per-chat /language)
calendar_client.py  Khmer Calendar API client (login, token refresh, day view)
config.py           .env loading + runtime settings persisted to config.json
requirements.txt    python-telegram-bot, anthropic, httpx, python-dotenv, tzdata
.env                Secrets (bot token, calendar login) — never commit this
config.json         Created at runtime: API keys, provider, chats, digest time
```

## Notes

- Timezone is `Asia/Phnom_Penh` everywhere (the Calendar API uses it too).
- LLM API keys are stored locally in `config.json` and shown only masked.
  Anyone who can message the bot can use its commands — for a real deployment,
  restrict the bot to your own chat id.
- If the calendar token expires, the client re-authenticates automatically.
