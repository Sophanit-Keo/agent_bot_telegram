"""AI Telegram Agent.

Connects a Telegram bot to:
  * the Khmer Calendar API  -> schedule summary + AI daily plan, sent
    automatically every day without manual intervention;
  * multiple LLM providers (Gemini / Claude / OpenAI) -> chat directly from
    Telegram, with API keys managed through bot commands.

Run:  python bot.py   (requires TELEGRAM_BOT_TOKEN in .env)
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import llm
import planner
from calendar_client import CalendarClient, CalendarError
from config import DEFAULT_MODELS, PROVIDER_LABELS, PROVIDERS, cfg
from i18n import LANG_ALIASES, t, tr
from memory import memories

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("ai-telegram-agent")

TZ = ZoneInfo(config.TIMEZONE)
TELEGRAM_LIMIT = 4096

PROVIDER_ALIASES = {
    "google": "gemini",
    "anthropic": "claude",
    "gpt": "openai",
    "chatgpt": "openai",
}

calendar = CalendarClient()

# Per-chat AI conversation history: chat_id -> deque of {"role", "content"}
chat_histories: dict[int, deque] = defaultdict(lambda: deque(maxlen=30))

# Short-lived cache of calendar day payloads used to ground the AI chat.
_day_cache: dict[str, tuple[float, dict]] = {}
DAY_CACHE_TTL = 300  # seconds


async def _cached_day(date_str: str, chat_id: int | None = None) -> dict:
    key = f"{chat_id}:{date_str}"
    hit = _day_cache.get(key)
    if hit and time.monotonic() - hit[0] < DAY_CACHE_TTL:
        return hit[1]
    day = await calendar.day(date_str, chat_id=chat_id)
    _day_cache[key] = (time.monotonic(), day)
    return day


# Cached display name of each chat's signed-in calendar user.
_user_names: dict[int, str] = {}


async def _account_name(chat_id: int) -> str | None:
    if chat_id in _user_names:
        return _user_names[chat_id]
    try:
        me = await calendar.me(chat_id=chat_id)
    except CalendarError:
        return None
    name = str((me or {}).get("name") or "").strip()
    if name:
        _user_names[chat_id] = name
    return name or None


def _drop_day_cache(chat_id: int) -> None:
    """Invalidate cached day payloads for a chat (after adding data / login)."""
    prefix = f"{chat_id}:"
    for key in [k for k in _day_cache if k.startswith(prefix)]:
        _day_cache.pop(key, None)

# Interface texts (help, sign-in prompt, labels) live in i18n.py in EN and KM.


# -- small helpers ------------------------------------------------------------------


def _resolve_provider(name: str) -> str | None:
    name = name.lower().strip()
    name = PROVIDER_ALIASES.get(name, name)
    return name if name in PROVIDERS else None


def _mask(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "•••"


def _parse_date_arg(args: list[str]) -> date:
    if args:
        return date.fromisoformat(args[0])
    return datetime.now(TZ).date()


def _split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split text into Telegram-sized chunks, preferring newline boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def _reply(update: Update, text: str, parse_mode: str | None = None) -> None:
    for chunk in _split_message(text):
        await update.effective_message.reply_text(chunk, parse_mode=parse_mode)


async def _require_signin(update: Update) -> bool:
    """True when this chat has a calendar account; otherwise prompt and block."""
    if cfg.get_account(update.effective_chat.id):
        return True
    await _reply(update, t(update.effective_chat.id, "signin"), ParseMode.HTML)
    return False


async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action=ChatAction.TYPING
        )
    except TelegramError:
        pass


# -- calendar / planning commands --------------------------------------------------


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not cfg.get_account(chat_id):
        # Not signed in yet: only show how to sign in (and /language).
        await _reply(update, t(chat_id, "signin"), ParseMode.HTML)
        return
    cfg.add_chat(chat_id)
    greeting = t(chat_id, "start_greeting", time=cfg.daily_time)
    await _reply(update, greeting + t(chat_id, "help"), ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    await _reply(update, t(update.effective_chat.id, "help"), ParseMode.HTML)


async def _send_calendar_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
    offset: int | None = None,
) -> None:
    if not await _require_signin(update):
        return
    if offset is not None:
        for_date = datetime.now(TZ).date() + timedelta(days=offset)
    else:
        try:
            for_date = _parse_date_arg(context.args)
        except ValueError:
            await _reply(update, "Please use the date format YYYY-MM-DD, e.g. /today 2026-07-15")
            return
    await _typing(update, context)
    try:
        day = await calendar.day(for_date.isoformat(), chat_id=update.effective_chat.id)
    except CalendarError as exc:
        await _reply(update, f"⚠️ Calendar problem: {exc}")
        return
    chat_id = update.effective_chat.id
    lang = cfg.get_language(chat_id)
    user_name = await _account_name(chat_id)
    if mode == "summary":
        await _reply(
            update, planner.build_summary(day, for_date, user_name, lang), ParseMode.HTML
        )
    elif mode == "plan":
        plan, source = await planner.generate_plan(day, for_date, user_name, lang)
        note = tr(lang, "planned_by", source=source) if source else tr(lang, "auto_plan")
        who = f"{html.escape(user_name)} — " if user_name else ""
        header = tr(
            lang,
            "plan_header",
            who=who,
            date=for_date.strftime("%d %B %Y"),
            note=html.escape(note),
        )
        await _reply(update, f"{header}\n{html.escape(plan)}", ParseMode.HTML)
    else:
        await _reply(
            update,
            await planner.build_digest(day, for_date, user_name, lang),
            ParseMode.HTML,
        )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_view(update, context, "digest")


async def cmd_tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_view(update, context, "digest", offset=1)


async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_view(update, context, "digest", offset=-1)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_view(update, context, "summary")


def _shifts_period(arg: str) -> tuple[date, date, str] | None:
    """Resolve 'month'/'year'/'YYYY-MM'/'YYYY'/'' to (start, end, label)."""
    today = datetime.now(TZ).date()
    arg = arg.strip().lower()
    if arg in ("", "month", "this month"):
        year, month = today.year, today.month
    elif arg in ("year", "this year"):
        start = date(today.year, 1, 1)
        return start, date(today.year, 12, 31), str(today.year)
    elif re.fullmatch(r"\d{4}", arg):
        return date(int(arg), 1, 1), date(int(arg), 12, 31), arg
    elif re.fullmatch(r"\d{4}-\d{2}", arg):
        year, month = int(arg[:4]), int(arg[5:7])
        if not 1 <= month <= 12:
            return None
    else:
        return None
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) - timedelta(days=1) if month == 12 else date(
        year, month + 1, 1
    ) - timedelta(days=1)
    return start, end, start.strftime("%B %Y")


async def _send_shifts(update: Update, context: ContextTypes.DEFAULT_TYPE, arg: str) -> None:
    """Working-schedule list for a month or year, from /work-schedule/days."""
    if not await _require_signin(update):
        return
    chat_id = update.effective_chat.id
    lang = cfg.get_language(chat_id)
    period = _shifts_period(arg)
    if period is None:
        await _reply(update, t(chat_id, "shifts_usage"))
        return
    start, end, label = period
    await _typing(update, context)
    try:
        days = await calendar.work_days(start.isoformat(), end.isoformat(), chat_id=chat_id)
    except CalendarError as exc:
        await _reply(update, f"⚠️ Calendar problem: {exc}")
        return
    working = [d for d in days if d.get("shift_template")]
    if not working:
        await _reply(update, tr(lang, "shifts_none", period=label), ParseMode.HTML)
        return
    lines = [tr(lang, "shifts_header", period=html.escape(label))]
    by_year = start.year != end.year or start.month != end.month  # year view -> month groups
    current_month = None
    for entry in working:
        day_date = date.fromisoformat(entry["date"])
        if by_year and day_date.strftime("%B %Y") != current_month:
            current_month = day_date.strftime("%B %Y")
            lines.append(f"\n<b>{current_month}</b>")
        shift = entry["shift_template"]
        times = ""
        if shift.get("start_time") and shift.get("end_time"):
            times = f" ({shift['start_time']}–{shift['end_time']})"
        lines.append(
            f"• {day_date.strftime('%a %d %b')} — "
            f"{html.escape(shift.get('name') or shift.get('code') or '?')}{times}"
        )
    lines.append(tr(lang, "shifts_total", n=len(working), off=len(days) - len(working)))
    await _reply(update, "\n".join(lines), ParseMode.HTML)


async def cmd_shifts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_shifts(update, context, " ".join(context.args or []))


# "check my schedule this month/year" in plain chat -> answer with real data
# instead of sending the huge range to the LLM.
_SHIFTS_WORDS = re.compile(r"schedule|shifts?|work|កាលវិភាគ|វេន|ការងារ", re.IGNORECASE)
_SHIFTS_MONTH = re.compile(r"\bthis month\b|\bmonth\b|ខែនេះ", re.IGNORECASE)
_SHIFTS_YEAR = re.compile(r"\bthis year\b|\byear\b|ឆ្នាំនេះ", re.IGNORECASE)


def _shifts_intent(text: str) -> str | None:
    if len(text) > 80 or not _SHIFTS_WORDS.search(text):
        return None
    if _SHIFTS_YEAR.search(text):
        return "year"
    if _SHIFTS_MONTH.search(text):
        return "month"
    return None


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_calendar_view(update, context, "plan")


async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    if not context.args:
        await _reply(
            update,
            f"Daily digest time is <b>{cfg.daily_time}</b> ({config.TIMEZONE}).\n"
            "Change it with /settime HH:MM",
            ParseMode.HTML,
        )
        return
    raw = context.args[0]
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError:
        await _reply(update, "Time must look like 06:30 (24-hour HH:MM).")
        return
    cfg.set_daily_time(parsed.strftime("%H:%M"))
    cfg.add_chat(update.effective_chat.id)
    await _reply(
        update,
        f"✅ Daily digest will be sent automatically at <b>{cfg.daily_time}</b> "
        f"({config.TIMEZONE}).",
        ParseMode.HTML,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    removed = cfg.remove_chat(update.effective_chat.id)
    await _reply(
        update,
        "🔕 This chat will no longer receive the daily digest. /start to re-subscribe."
        if removed
        else "This chat was not subscribed. /start to subscribe.",
    )


# -- personal calendar accounts & dynamic input ---------------------------------------


def _parse_when(word: str) -> date:
    """'today' / 'tomorrow' / 'YYYY-MM-DD' -> date (raises ValueError)."""
    lowered = word.lower()
    if lowered == "today":
        return datetime.now(TZ).date()
    if lowered == "tomorrow":
        return datetime.now(TZ).date() + timedelta(days=1)
    return date.fromisoformat(word)


async def cmd_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) != 2:
        await _reply(
            update,
            "Usage: /login <email> <password>\n"
            "Connects YOUR calendar account to this chat — events, notes and the "
            "daily digest become personal.\n⚠️ Use this in a private chat.",
        )
        return
    email, password = context.args[0], context.args[1]
    try:
        await update.effective_message.delete()  # hide the password ASAP
    except TelegramError:
        pass
    try:
        await calendar.login(email, password)
    except CalendarError as exc:
        await context.bot.send_message(chat_id, f"⚠️ {exc}")
        return
    cfg.set_account(chat_id, email, password)
    cfg.add_chat(chat_id)  # signed in -> subscribe to the daily digest
    calendar.drop_token(chat_id)
    _drop_day_cache(chat_id)
    _user_names.pop(chat_id, None)
    await context.bot.send_message(
        chat_id,
        f"✅ Connected calendar account <b>{html.escape(email)}</b>.\n"
        "This chat now sees only that account's events and notes. /logout to disconnect.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await _reply(
            update,
            "Usage: /register <email> <password> [your name]\n"
            "Creates a NEW calendar account and connects it to this chat.\n"
            "⚠️ Use this in a private chat.",
        )
        return
    email, password = context.args[0], context.args[1]
    name = " ".join(context.args[2:]) or (update.effective_user.full_name or "Telegram User")
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
    try:
        await calendar.register(name, email, password)
    except CalendarError as exc:
        await context.bot.send_message(chat_id, f"⚠️ {exc}")
        return
    cfg.set_account(chat_id, email, password)
    cfg.add_chat(chat_id)  # signed in -> subscribe to the daily digest
    calendar.drop_token(chat_id)
    _drop_day_cache(chat_id)
    _user_names[chat_id] = name
    await context.bot.send_message(
        chat_id,
        f"🎉 Calendar account created for <b>{html.escape(name)}</b> "
        f"(<b>{html.escape(email)}</b>) and connected to this chat.\n"
        "Add your first event with /addevent!",
        parse_mode=ParseMode.HTML,
    )


async def cmd_logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    removed = cfg.remove_account(chat_id)
    calendar.drop_token(chat_id)
    _drop_day_cache(chat_id)
    _user_names.pop(chat_id, None)
    await _reply(
        update,
        "👋 Signed out. You need to /login (or /register) again before using the bot."
        if removed
        else "You are not signed in. Use /login <email> <password> or /register.",
    )


async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    account = cfg.get_account(update.effective_chat.id)
    if account:
        text = (
            f"📇 Signed in as <b>{html.escape(account['email'])}</b>.\n"
            "/logout to sign out."
        )
        await _reply(update, text, ParseMode.HTML)
    else:
        await _reply(update, t(update.effective_chat.id, "signin"), ParseMode.HTML)


_TIME_RANGE = re.compile(r"^(\d{1,2}:\d{2})(?:-(\d{1,2}:\d{2}))?$")

ADDEVENT_USAGE = (
    "Usage: /addevent <date> <time> <title> [@ location]\n"
    "date: YYYY-MM-DD, today or tomorrow · time: HH:MM or HH:MM-HH:MM\n"
    "Examples:\n"
    "/addevent tomorrow 14:00-15:30 Team meeting @ IT STEP\n"
    "/addevent 2026-07-20 09:00 Math exam"
)


async def cmd_addevent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    chat_id = update.effective_chat.id
    args = context.args
    if len(args) < 3:
        await _reply(update, ADDEVENT_USAGE)
        return
    try:
        event_date = _parse_when(args[0])
    except ValueError:
        await _reply(update, ADDEVENT_USAGE)
        return
    match = _TIME_RANGE.match(args[1])
    if not match:
        await _reply(update, ADDEVENT_USAGE)
        return
    start_dt = datetime.combine(
        event_date, datetime.strptime(match.group(1), "%H:%M").time()
    )
    if match.group(2):
        end_dt = datetime.combine(
            event_date, datetime.strptime(match.group(2), "%H:%M").time()
        )
        if end_dt <= start_dt:
            await _reply(update, "End time must be after the start time.")
            return
    else:
        end_dt = start_dt + timedelta(hours=1)  # default duration: 1 hour

    title, _, location = " ".join(args[2:]).partition("@")
    title, location = title.strip(), location.strip()
    if not title:
        await _reply(update, ADDEVENT_USAGE)
        return

    payload: dict = {
        "title": title,
        "starts_at": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "ends_at": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if location:
        payload["location"] = location
    await _typing(update, context)
    try:
        created = await calendar.create_event(payload, chat_id=chat_id)
    except CalendarError as exc:
        await _reply(update, f"⚠️ {exc}")
        return
    _drop_day_cache(chat_id)
    place = f" 📍{html.escape(location)}" if location else ""
    await _reply(
        update,
        t(
            chat_id,
            "event_added",
            title=html.escape(str(created.get("title", title))),
            date=event_date.strftime("%d %B %Y"),
            time=f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}",
            place=place,
        ),
        ParseMode.HTML,
    )


async def cmd_addnote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    chat_id = update.effective_chat.id
    args = context.args
    if not args:
        await _reply(
            update,
            "Usage: /addnote [date] <text>\n"
            "Examples:\n/addnote Buy notebooks\n/addnote tomorrow Call the teacher",
        )
        return
    try:
        note_date = _parse_when(args[0])
        text = " ".join(args[1:])
    except ValueError:
        note_date = datetime.now(TZ).date()
        text = " ".join(args)
    if not text:
        await _reply(update, "The note text is empty — /addnote [date] <text>")
        return
    await _typing(update, context)
    try:
        await calendar.create_note(note_date.isoformat(), text, chat_id=chat_id)
    except CalendarError as exc:
        await _reply(update, f"⚠️ {exc}")
        return
    _drop_day_cache(chat_id)
    await _reply(
        update,
        t(
            chat_id,
            "note_saved",
            date=note_date.strftime("%d %B %Y"),
            text=html.escape(text),
        ),
        ParseMode.HTML,
    )


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        current = "ភាសាខ្មែរ" if cfg.get_language(chat_id) == "km" else "English"
        await _reply(update, t(chat_id, "lang_usage", current=current))
        return
    lang = LANG_ALIASES.get(context.args[0].lower())
    if not lang:
        await _reply(update, t(chat_id, "lang_usage", current=cfg.get_language(chat_id)))
        return
    cfg.set_language(chat_id, lang)
    await _reply(update, tr(lang, "lang_set"))


# -- LLM management commands ---------------------------------------------------------


async def cmd_setkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    if len(context.args) < 2:
        await _reply(
            update,
            "Usage: /setkey <provider> <api-key>\nProviders: gemini, claude, openai\n"
            "⚠️ Send this in a private chat with the bot.",
        )
        return
    provider = _resolve_provider(context.args[0])
    if not provider:
        await _reply(update, "Unknown provider. Use one of: gemini, claude, openai")
        return
    key = context.args[1].strip()
    cfg.set_key(provider, key)
    # Remove the message containing the raw key from the chat, when possible.
    deleted = True
    try:
        await update.effective_message.delete()
    except TelegramError:
        deleted = False
    text = (
        f"🔑 API key for <b>{PROVIDER_LABELS[provider]}</b> saved ({_mask(key)}).\n"
        f"Model: <code>{html.escape(cfg.model_for(provider))}</code>"
    )
    if not deleted:
        text += "\n⚠️ I could not delete your message — remove it manually to protect the key."
    await context.bot.send_message(update.effective_chat.id, text, parse_mode=ParseMode.HTML)


async def cmd_delkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    if not context.args:
        await _reply(update, "Usage: /delkey <provider>")
        return
    provider = _resolve_provider(context.args[0])
    if not provider:
        await _reply(update, "Unknown provider. Use one of: gemini, claude, openai")
        return
    removed = cfg.delete_key(provider)
    await _reply(
        update,
        f"🗑 Key for {PROVIDER_LABELS[provider]} removed."
        if removed
        else f"No key was stored for {PROVIDER_LABELS[provider]}.",
    )


async def cmd_keys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    lines = ["🔐 <b>Configured providers</b>"]
    for provider in PROVIDERS:
        key = cfg.get_key(provider)
        active = " ✅ active" if provider == cfg.provider else ""
        status = _mask(key) if key else "— no key (/setkey)"
        lines.append(
            f"• <b>{PROVIDER_LABELS[provider]}</b>: {status} · "
            f"<code>{html.escape(cfg.model_for(provider))}</code>{active}"
        )
    await _reply(update, "\n".join(lines), ParseMode.HTML)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    if not context.args:
        lines = [
            f"🧠 Active AI: <b>{PROVIDER_LABELS[cfg.provider]}</b> "
            f"(<code>{html.escape(cfg.model_for(cfg.provider))}</code>)",
            "",
            "Switch with /model gemini · /model claude · /model openai",
        ]
        await _reply(update, "\n".join(lines), ParseMode.HTML)
        return
    provider = _resolve_provider(context.args[0])
    if not provider:
        await _reply(update, "Unknown provider. Use one of: gemini, claude, openai")
        return
    cfg.set_provider(provider)
    text = (
        f"✅ Chat and planning now use <b>{PROVIDER_LABELS[provider]}</b> "
        f"(<code>{html.escape(cfg.model_for(provider))}</code>)."
    )
    if not cfg.get_key(provider):
        text += f"\n⚠️ No API key stored yet — add one with /setkey {provider} <key>"
    await _reply(update, text, ParseMode.HTML)


async def cmd_setmodel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    if len(context.args) < 2:
        defaults = ", ".join(f"{p}: {m}" for p, m in DEFAULT_MODELS.items())
        await _reply(update, f"Usage: /setmodel <provider> <model-id>\nDefaults — {defaults}")
        return
    provider = _resolve_provider(context.args[0])
    if not provider:
        await _reply(update, "Unknown provider. Use one of: gemini, claude, openai")
        return
    model = context.args[1].strip()
    cfg.set_model(provider, model)
    await _reply(
        update,
        f"✅ {PROVIDER_LABELS[provider]} will use <code>{html.escape(model)}</code>.",
        ParseMode.HTML,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    chat_histories.pop(update.effective_chat.id, None)
    await _reply(update, "🧹 Conversation history cleared. (Long-term memory kept — see /memory)")


# -- long-term memory commands -------------------------------------------------------


async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    text = " ".join(context.args)
    if not text:
        await _reply(update, "Usage: /remember <something to keep>, e.g. /remember I study at IT STEP")
        return
    if memories.add(update.effective_chat.id, text):
        await _reply(update, f"💾 Got it, I'll remember: {text}")
    else:
        await _reply(update, "I already remember that. 🙂 See /memory")


async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    facts = memories.list(update.effective_chat.id)
    if not facts:
        await _reply(
            update,
            "🧠 Memory is empty. Tell me things in chat, or use /remember <fact>.",
        )
        return
    lines = ["🧠 <b>What I remember</b>"]
    lines += [f"{i}. {html.escape(fact)}" for i, fact in enumerate(facts, start=1)]
    lines.append("\nForget one with /forget <number>, or everything with /forget all")
    await _reply(update, "\n".join(lines), ParseMode.HTML)


async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_signin(update):
        return
    chat_id = update.effective_chat.id
    if not context.args:
        await _reply(update, "Usage: /forget <number>  (see numbers in /memory)  or  /forget all")
        return
    if context.args[0].lower() == "all":
        count = memories.clear(chat_id)
        await _reply(update, f"🧹 Forgot {count} thing(s)." if count else "Memory was already empty.")
        return
    try:
        index = int(context.args[0])
    except ValueError:
        await _reply(update, "Please give a number from /memory, or 'all'.")
        return
    removed = memories.forget(chat_id, index)
    await _reply(
        update,
        f"🗑 Forgot: {removed}" if removed else "No memory with that number — check /memory.",
    )


# -- AI chat ---------------------------------------------------------------------------


CHAT_SYSTEM_PROMPT = (
    "You are a friendly personal assistant living inside a Telegram bot. You manage "
    "the user's calendar and daily plans, and you can also chat about anything else.\n"
    "Current date and time: {now} (timezone Asia/Phnom_Penh, Cambodia).\n\n"
    "REAL CALENDAR DATA from the user's calendar (today and tomorrow):\n"
    "{calendar_json}\n\n"
    "THINGS YOU REMEMBER ABOUT THE USER:\n{memories}\n\n"
    "How to behave:\n"
    "- Sound like a warm, helpful friend, not a formal robot. Keep small talk short "
    "and natural; give more detail only when the question needs it. {language_rule}\n"
    "- For questions about schedule, events, free time, holidays or planning, base "
    "your answer ONLY on the calendar data above and mention concrete times. If the "
    "question is about a date not included above, say so and suggest the command "
    "/today YYYY-MM-DD instead of guessing.\n"
    "- Use what you remember about the user to personalise answers.\n"
    "- When the user shares a lasting fact, preference, goal or deadline worth "
    "keeping (for example their name, what they study, a due date), add one line at "
    "the VERY END of your reply exactly in this form: [REMEMBER: short fact]. "
    "Only for lasting facts - never for small talk or questions.\n"
    "- Plain text only: no markdown, no asterisks, no headings."
)

_REMEMBER_TAG = re.compile(r"\[REMEMBER:\s*(.+?)\]", re.IGNORECASE | re.DOTALL)


def _extract_memories(answer: str) -> tuple[str, list[str]]:
    """Pull [REMEMBER: ...] tags out of an LLM reply; return (clean_text, facts)."""
    facts = [" ".join(fact.split()) for fact in _REMEMBER_TAG.findall(answer)]
    cleaned = _REMEMBER_TAG.sub("", answer).strip()
    return cleaned, facts


async def _chat_context_json(today: date, chat_id: int) -> str:
    """Today's + tomorrow's calendar data as compact JSON for the system prompt.
    Best effort: the chat keeps working even if the Calendar API is down."""
    try:
        tomorrow = today + timedelta(days=1)
        data = {
            "today": planner.day_context(
                await _cached_day(today.isoformat(), chat_id), today
            ),
            "tomorrow": planner.day_context(
                await _cached_day(tomorrow.isoformat(), chat_id), tomorrow
            ),
        }
    except CalendarError as exc:
        data = {"calendar_error": f"calendar unavailable right now: {exc}"}
    return json.dumps(data, ensure_ascii=False)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return
    if not await _require_signin(update):
        return
    intent = _shifts_intent(message.text)
    if intent:
        await _send_shifts(update, context, intent)
        return
    chat_id = update.effective_chat.id
    history = chat_histories[chat_id]
    history.append({"role": "user", "content": message.text})
    await _typing(update, context)

    now = datetime.now(TZ)
    remembered = memories.list(chat_id)
    language_rule = (
        "Always reply in Khmer (ភាសាខ្មែរ), unless the user clearly asks for another language."
        if cfg.get_language(chat_id) == "km"
        else "Reply in the same language the user writes in."
    )
    system = CHAT_SYSTEM_PROMPT.format(
        now=now.strftime("%A %d %B %Y, %H:%M"),
        calendar_json=await _chat_context_json(now.date(), chat_id),
        memories="\n".join(f"- {fact}" for fact in remembered) or "(nothing saved yet)",
        language_rule=language_rule,
    )
    try:
        answer = await llm.chat(cfg.provider, list(history), system=system)
    except llm.LLMNotConfigured as exc:
        history.pop()
        await _reply(update, f"🔑 {exc}")
        return
    except llm.LLMError as exc:
        history.pop()
        await _reply(update, f"⚠️ {exc}")
        return

    answer, facts = _extract_memories(answer)
    saved = [fact for fact in facts if memories.add(chat_id, fact)]
    history.append({"role": "assistant", "content": answer})
    if saved:
        answer += "\n\n💾 Saved to memory: " + "; ".join(saved)
    await _reply(update, answer)  # plain text: LLM output is not trusted HTML


# -- automatic daily digest -------------------------------------------------------------


async def _broadcast_digest(app: Application) -> None:
    chats = cfg.chats
    if not chats:
        logger.info("Daily digest due, but no chats are subscribed")
        return
    today = datetime.now(TZ).date()
    delivered = 0
    for chat_id in chats:
        # Only signed-in chats receive a digest, built from THEIR calendar account.
        if not cfg.get_account(chat_id):
            logger.info("Skipping digest for chat %s (not signed in)", chat_id)
            continue
        lang = cfg.get_language(chat_id)
        header = tr(lang, "digest_header")
        try:
            day = await calendar.day(today.isoformat(), chat_id=chat_id)
            text = await planner.build_digest(
                day, today, await _account_name(chat_id), lang
            )
        except CalendarError as exc:
            text = f"⚠️ Good morning! I could not load today's calendar: {html.escape(str(exc))}"
        try:
            for chunk in _split_message(header + text):
                await app.bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)
            delivered += 1
        except Forbidden:
            logger.info("Chat %s blocked the bot - unsubscribing it", chat_id)
            cfg.remove_chat(chat_id)
        except TelegramError as exc:
            logger.warning("Could not deliver digest to chat %s: %s", chat_id, exc)
    logger.info("Daily digest delivered to %d chat(s)", delivered)


async def _daily_loop(app: Application) -> None:
    """Fire the digest once per day at cfg.daily_time (checked every 20 s, so
    /settime changes take effect immediately without rescheduling anything)."""
    sent_on: date | None = None
    logger.info("Daily digest scheduler running (time=%s %s)", cfg.daily_time, config.TIMEZONE)
    while True:
        now = datetime.now(TZ)
        if sent_on != now.date() and now.strftime("%H:%M") == cfg.daily_time:
            sent_on = now.date()
            try:
                await _broadcast_digest(app)
            except Exception:
                logger.exception("Daily digest broadcast failed")
        await asyncio.sleep(20)


# -- wiring -------------------------------------------------------------------------------


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error while processing update", exc_info=context.error)


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("today", "Schedule summary + AI daily plan"),
            BotCommand("tomorrow", "Summary + plan for tomorrow"),
            BotCommand("yesterday", "Summary + plan for yesterday"),
            BotCommand("addevent", "Add an event: /addevent tomorrow 14:00 Title"),
            BotCommand("addnote", "Add a note: /addnote [date] text"),
            BotCommand("login", "Connect your calendar account"),
            BotCommand("account", "Which calendar account this chat uses"),
            BotCommand("summary", "Schedule summary"),
            BotCommand("plan", "AI daily plan"),
            BotCommand("model", "Show / switch AI provider"),
            BotCommand("language", "Language / ភាសា: en or km"),
            BotCommand("memory", "What the bot remembers"),
            BotCommand("remember", "Save a fact: /remember <fact>"),
            BotCommand("forget", "Forget a fact: /forget <n|all>"),
            BotCommand("keys", "List configured API keys"),
            BotCommand("setkey", "Save an API key: /setkey claude <key>"),
            BotCommand("settime", "Set daily digest time (HH:MM)"),
            BotCommand("reset", "Clear AI chat history"),
            BotCommand("stop", "Unsubscribe from daily digest"),
            BotCommand("help", "Show help"),
        ]
    )
    app.create_task(_daily_loop(app))
    logger.info("Bot is up. Active AI provider: %s", cfg.provider)


async def post_shutdown(app: Application) -> None:
    await calendar.close()


def build_application(for_polling: bool = True) -> Application:
    """Build the PTB application with every handler registered.

    Used by main() for local long polling, and by api/webhook.py on Vercel
    (webhook mode - no post_init/post_shutdown, no background daily loop:
    the digest comes from Vercel Cron hitting api/cron.py instead).
    """
    builder = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN)
    if for_polling:
        builder = builder.post_init(post_init).post_shutdown(post_shutdown)
    app = builder.build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("shifts", cmd_shifts))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("login", cmd_login))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("logout", cmd_logout))
    app.add_handler(CommandHandler("account", cmd_account))
    app.add_handler(CommandHandler("addevent", cmd_addevent))
    app.add_handler(CommandHandler("addnote", cmd_addnote))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("setkey", cmd_setkey))
    app.add_handler(CommandHandler("delkey", cmd_delkey))
    app.add_handler(CommandHandler("keys", cmd_keys))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("setmodel", cmd_setmodel))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CommandHandler("remember", cmd_remember))
    app.add_handler(CommandHandler("memory", cmd_memory))
    app.add_handler(CommandHandler("forget", cmd_forget))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is missing.\n"
            "1. Open Telegram, talk to @BotFather, send /newbot and follow the steps.\n"
            "2. Paste the token into the .env file: TELEGRAM_BOT_TOKEN=123456:ABC...\n"
            "3. Run this again."
        )
    app = build_application(for_polling=True)
    logger.info("Starting polling…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
