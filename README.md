# AI Telegram Agent

An AI agent connected to a Telegram bot that automates schedule management and
provides AI-powered conversations.

## What it does

| Requirement | How it is covered |
|---|---|
| **Telegram bot integration** | `bot.py` runs a bot (long polling) that answers commands, chats, and pushes notifications on its own. |
| **Calendar integration** | `calendar_client.py` authenticates against the Khmer Calendar API (`https://api-calender-sigma.vercel.app/api/v1`) with a revocable per-chat bearer token and reads events, notes, holidays, and work shifts. Expired sessions ask the user to sign in again. |
| **Schedule summary** | `planner.build_summary()` produces a concise overview: events with times/locations, busy-hours total, holidays, Khmer lunar date, notes. |
| **Complete daily plan** | `planner.generate_plan()` asks the selected AI for a morning-to-night plan (work blocks, meals, breaks, free time) around the fixed calendar events. If no AI key is configured, a built-in deterministic planner produces the plan instead, so the digest always works. |
| **Automatic daily sending** | A scheduler inside the bot sends the digest (summary + plan) every day at the configured time (default **06:30**, `Asia/Phnom_Penh`) to every subscribed chat — no manual action needed. |
| **Multi-LLM integration** | `llm.py` talks to **Google Gemini**, **Anthropic Claude** (official SDK) and **OpenAI GPT**, with multiple keys and automatic same-provider failover. |
| **Keys managed via Telegram** | `/setkey`, `/delkey`, `/keys`, `/model`, `/setmodel` — each provider has an ordered key pool stored in `config.json` (git-ignored); the bot deletes messages containing raw keys when it can. |
| **Chat with the selected AI** | Any plain text message is answered by the active provider in a natural, friendly tone, with per-chat conversation history (`/reset` clears it). The chat is **grounded in real data**: today's and tomorrow's calendar are injected into every request, so questions like *"am I free tomorrow afternoon?"* are answered from the actual schedule. |
| **Long-term memory** | The bot remembers lasting facts across restarts (`memory.py` → `memory.json`). Facts are saved automatically when you mention them in chat (the AI tags them with `[REMEMBER: ...]`), or explicitly via `/remember`. Manage with `/memory` and `/forget`. |
| **English / Khmer** | `/language en` or `/language km` per chat (`i18n.py`). Switches the interface (help, sign-in prompt, schedule summary, digest, confirmations), the built-in fallback plan, and instructs the AI to chat and plan in Khmer. |
| **Dynamic input per user** | **Sign-in is required**: every private chat must connect its own Calendar API account (`/login` or `/register`) before using the bot. The password is used only to obtain a revocable access token and is not persisted. After sign-in, events, notes, digest and AI answers use that personal calendar. |

## Setup

1. **Create the bot** — in Telegram, open **@BotFather** → `/newbot` → choose a
   name and username → copy the token.
2. **Configure** — copy `.env.example` to `.env` and paste the token:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAF...your-token...
   ```
   Keep `.env` private; it is ignored by Git.
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
   /login                                      (existing account; guided flow)
   /register me@example.com use-a-strong-password My Name
   ```
   The chat is now subscribed to the automatic daily digest of that account.
   Until sign-in succeeds, the Telegram command menu contains only `/login`
   and `/register`, and all calendar, AI, memory, and settings commands are blocked.
5. **(Optional) add an AI key** so plans and chat are AI-powered:
   ```
   /setkey gemini  AIza-key-1 AIza-key-2  (from https://aistudio.google.com/apikey)
   /setkey claude  sk-ant-key-1            (from https://platform.claude.com)
   /setkey openai  sk-key-1 sk-key-2       (from https://platform.openai.com)
   /model claude                  (choose the active provider)
   ```
   If a key is rejected, out of quota/rate-limited, or encounters a temporary
   network/API error, the next key for that provider is tried automatically.

## Commands

| Command | Description |
|---|---|
| `/start` | Subscribe this chat to the daily digest + show help |
| `/today [YYYY-MM-DD]` | Schedule summary **and** AI daily plan |
| `/tomorrow` | Summary + plan for tomorrow |
| `/yesterday` | Summary + plan for yesterday |
| `/summary [YYYY-MM-DD]` | Schedule summary only |
| `/plan [YYYY-MM-DD]` | Daily plan only |
| `/shifts [month\|year\|YYYY-MM\|YYYY]` | Working-schedule list for a month or year (also triggered by chatting "check my schedule this month/year") |
| `/settime HH:MM` | Set the automatic digest time (24 h, Asia/Phnom_Penh) |
| `/stop` | Unsubscribe from the daily digest |
| `/addevent <date> <time> <title> [@ place]` | Add an event (`/addevent tomorrow 14:00-15:30 Meeting @ IT STEP`) |
| `/addnote [date] <text>` | Add a note (date defaults to today) |
| `/login` | In a private chat, connect your calendar account step by step. The bot deletes credential messages and stores the issued access token, not your password. |
| `/cancel` | Cancel an interactive sign-in |
| `/register <email> <password> [name]` | Create a new calendar account and connect it |
| `/account` | Show which calendar account this chat uses |
| `/logout` | Disconnect the personal account; sign-in is required to continue |
| *(any text)* | Chat with the selected AI model (calendar-aware, friendly tone) |
| `/remember <fact>` | Save a fact to long-term memory |
| `/memory` | List everything the bot remembers |
| `/forget <n\|all>` | Forget one fact (by number) or everything |
| `/model [provider]` | Show or switch the active AI (gemini / claude / openai) |
| `/setkey <provider> <key> [more-keys...]` | Add one or more keys to a provider's failover pool (use a private chat!) |
| `/delkey <provider> <number\|all>` | Delete one numbered key (see `/keys`) or the complete pool |
| `/keys` | List providers, numbered masked key pools, and models |
| `/setmodel <provider> <model>` | Override the model id (see `config.py` for current defaults) |
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
.env                Bot/deployment secrets and optional API keys — never commit
config.json         Sensitive runtime state: access/API tokens, chats, settings
```

## Deploy to Vercel (optional)

Vercel is serverless, so the bot runs there in **webhook mode** instead of
polling, the daily digest comes from **Vercel Cron**, and state is stored in
**Upstash Redis** (Vercel's filesystem is wiped between requests).

Files involved: `app.py` (ASGI entrypoint serving `/api/webhook` for Telegram
updates and `/api/cron` for the daily digest), `vercel.json` (cron schedule,
`30 23 * * *` UTC = 06:30 Phnom Penh), `storage.py` (Redis-or-file state).

1. **Create a free Upstash Redis** database (https://upstash.com or the
   Vercel Marketplace → Upstash) and copy `UPSTASH_REDIS_REST_URL` and
   `UPSTASH_REDIS_REST_TOKEN`. Without them, logins/keys/memory reset
   constantly on Vercel.
2. **Import the project** into Vercel (push to GitHub → vercel.com → New
   Project, or `npx vercel` in this folder).
3. **Set environment variables** in the Vercel project settings.
   Required: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `CRON_SECRET`,
   `UPSTASH_REDIS_REST_URL`, and `UPSTASH_REDIS_REST_TOKEN`. Optional: `GEMINI_API_KEY` etc. (or use
   `/setkey` in the bot), `TIMEZONE`, `CALENDAR_BASE_URL` (defaults to the
   right URL).
   `CALENDAR_EMAIL`/`CALENDAR_PASSWORD` are **not needed** — every user signs
   in with their own account via `/login`, stored per chat in Redis.
4. **Deploy**, then point Telegram at the webhook (replace the token/URL):
   ```
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" -d "url=https://<your-app>.vercel.app/api/webhook" -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
   ```
5. Done — the bot answers via the webhook, and Vercel Cron sends the digest
   daily at 06:30 Phnom Penh time.

**Switching back to local:** Telegram allows only one delivery method, so
before running `python bot.py` locally again, remove the webhook:
```
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"
```

Limitations on Vercel: the digest time is fixed by `vercel.json` (the
`/settime` command does not change Vercel's cron; on the free Hobby plan cron
timing can drift within the hour), and short-term chat history may reset
between messages (long-term `/memory` persists in Redis).

## Notes

- Timezone is `Asia/Phnom_Penh` everywhere (the Calendar API uses it too).
- LLM API keys are stored locally in `config.json` and shown only masked. Multiple
  keys can also be supplied as comma-separated `GEMINI_API_KEYS`,
  `CLAUDE_API_KEYS`, or `OPENAI_API_KEYS` environment variables.
  Anyone who can message the bot can use its commands — for a real deployment,
  restrict the bot to your own chat id.
- If a calendar token expires, the bot asks that user to `/login` again; passwords are never persisted.
