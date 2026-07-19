# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An AI agent wired to a Telegram bot (`python-telegram-bot`) that reads a user's
calendar from the Khmer Calendar API, sends a daily schedule + AI-generated plan
every morning, and lets the user chat with a calendar-grounded LLM (Gemini,
Claude, or OpenAI) from Telegram. Runs either as a local long-polling process or
as a Vercel serverless function (webhook + cron).

## Commands

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python bot.py        # run locally (long polling)
run.bat                            # same, auto-creates the venv first (Windows)
```

There is no test suite, linter, or build step configured in this repo.

Local secrets go in `.env` (copy from `.env.example`); runtime state the bot
manages itself (API keys added via `/setkey`, calendar tokens, subscribed
chats, daily send time) persists to `config.json` / `memory.json`, both
git-ignored.

Before switching between local polling and the Vercel webhook, Telegram only
allows one delivery method at a time:
```
curl "https://api.telegram.org/bot<TOKEN>/deleteWebhook"     # before running bot.py locally
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" -d "url=https://<app>.vercel.app/api/webhook" -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

## Architecture

**Two entrypoints, one `Application`.** `bot.build_application(for_polling=...)`
builds the entire PTB `Application` (all handlers) and is shared by both
run modes:
- `bot.py main()` — local long polling (`for_polling=True`, registers
  `post_init`/`post_shutdown` and the in-process `_daily_loop` scheduler).
- `app.py` — Vercel ASGI entrypoint (`for_polling=False`). Routes
  `POST /api/webhook` (Telegram updates, HMAC-checked against
  `TELEGRAM_WEBHOOK_SECRET`) and `GET /api/cron` (daily digest trigger,
  bearer-checked against `CRON_SECRET`, driven by `vercel.json`'s cron
  schedule) to the same handler graph. The PTB `Application` is cached at
  module level so warm Vercel invocations reuse it; there is no background
  loop here since Vercel Cron replaces `_daily_loop`.

**Storage backend swaps automatically.** `storage.py` is the only place that
knows about persistence: local JSON files (`config.json`, `memory.json`) if
`UPSTASH_REDIS_REST_URL`/`_TOKEN` (or Vercel's `KV_REST_API_*` equivalents)
aren't set, Upstash Redis via REST otherwise — required on Vercel since its
filesystem is wiped between invocations. `config.py` (`cfg`, a thread-safe
singleton) and `memory.py` (`memories`) both sit on top of `storage.load`/`save`
and are the only state-mutation surfaces the rest of the code should use.

**Per-chat sign-in gate.** Every chat must connect its own Khmer Calendar API
account via `/login` or `/register` before anything else works — there is no
shared service account. `auth_gate` (`bot.py`) runs as a `group=-1` handler in
front of every other handler and raises `ApplicationHandlerStop` for unsigned
chats except `/start`, `/login`, `/register`, or plain text while a guided
login flow (`cfg.get_login_flow`) is in progress. `_set_command_menu` swaps the
visible Telegram command menu between `AUTH_COMMANDS` and `FULL_COMMANDS` to
match. `CalendarClient` stores one bearer token per chat (never the password)
and transparently re-authenticates on a 401 or migrates legacy
password-in-config records to token-only on first use.

**Multi-provider LLM gateway with same-provider failover.** `llm.chat(provider,
messages, system=...)` is the single entrypoint for Gemini/Claude/OpenAI/Anajak
(`config.PROVIDERS`). `anajak` reaches Claude through a third-party proxy
(`ANAJAK_BASE_URL`, default `https://api.anajaklabs.dev`) at `POST /v1/messages`
that accepts an Anthropic-shaped request body but replies with an
OpenAI-shaped chat-completion body (`choices[0].message.content`) — so
`llm._anajak()` is its own REST call parsed like `_openai()`, not a reuse of
`llm._claude()`'s (Anthropic-shaped) response parsing. It's a separate
provider from `claude` (not merged into it) since each keeps its own key pool
and endpoint; useful when direct Anthropic access isn't available.
`config.cfg` holds an ordered key pool per provider; `llm.py` tries the last
successful key first, then walks the rest of the pool on `LLMKeyUnavailable`
(auth/rate-limit/5xx/network errors), raising `LLMError` only once every key
has failed. `LLMNotConfigured` (no keys at all) is caught
by callers to fall back to non-AI behavior — see `planner.generate_plan`,
which always falls back to a deterministic plan (`_fallback_plan`) so the
daily digest never fails to send even with zero AI keys configured.

**Calendar-grounded chat.** Plain-text messages (`on_text`) are answered by
the active provider with the day's calendar JSON (`planner.day_context`,
today + tomorrow) injected into the system prompt alongside per-chat
long-term memory facts, so questions like "am I free tomorrow?" are answered
from real data rather than hallucinated. The LLM can append
`[REMEMBER: fact]` to a reply to save a long-term memory automatically;
`_extract_memories` strips the tag before the reply is shown to the user.

**i18n.** `i18n.py` holds English/Khmer string tables; `tr(lang, key, **kwargs)`
and `t(chat_id, key, **kwargs)` (looks up `cfg.get_language(chat_id)`) are used
everywhere user-facing text is built, including inside `planner.py`'s summary
and fallback-plan builders — new user-facing strings should go through this
table rather than being inlined.

## Working in this repo

- `config.json` and `memory.json` contain live secrets (calendar tokens, LLM
  API keys) when running locally — never read/print/commit their contents.
- Timezone is `Asia/Phnom_Penh` everywhere (`config.TIMEZONE`); the Calendar
  API assumes it too.
- `/settime` only affects local polling mode's `_daily_loop`; on Vercel the
  digest time is fixed by `vercel.json`'s cron schedule.
