"""Configuration for the AI Telegram agent.

Secrets and bootstrap values come from .env; runtime state that the bot
manages itself (API keys set via /setkey, calendar access tokens, chosen
provider, subscribed chats, daily send time) is persisted to config.json.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import storage  # after load_dotenv so UPSTASH_* from .env are visible

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CALENDAR_BASE_URL = os.getenv(
    "CALENDAR_BASE_URL", "https://api-calender-sigma.vercel.app/api/v1"
).rstrip("/")
CALENDAR_EMAIL = os.getenv("CALENDAR_EMAIL", "").strip()
CALENDAR_PASSWORD = os.getenv("CALENDAR_PASSWORD", "")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Phnom_Penh").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
ANAJAK_BASE_URL = os.getenv("ANAJAK_BASE_URL", "https://api.anajaklabs.dev").rstrip("/")

PROVIDERS = ("gemini", "claude", "openai", "anajak")

PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
    "openai": "OpenAI GPT",
    "anajak": "Claude (Anajak proxy)",
}

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash-lite",
    "claude": "claude-opus-4-8",
    "openai": "gpt-4o-mini",
    "anajak": "claude-opus-4-8",
}

_DEFAULTS = {
    "provider": "gemini",   # active LLM provider for chat + planning
    "api_keys": {},          # provider -> ordered list of API keys
    "models": {},            # provider -> model id override
    "daily_time": "06:30",   # HH:MM local time for the automatic daily digest
    "last_digest_date": "",  # YYYY-MM-DD; prevents duplicate sends after restarts
    "chats": [],             # Telegram chat ids subscribed to the daily digest
    "accounts": {},          # chat_id (str) -> personal calendar account {email, token}
    "languages": {},         # chat_id (str) -> interface language: "en" | "km"
}


class Config:
    """Thread-safe runtime configuration persisted to config.json."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = json.loads(json.dumps(_DEFAULTS))  # deep copy
        loaded = storage.load("config")
        if isinstance(loaded, dict):
            self._data.update(loaded)
        self._normalize()
        # Environment keys join the persisted pool. The singular variable is
        # retained for backward compatibility; *_API_KEYS accepts comma/newline
        # separated keys for automatic failover.
        for provider in PROVIDERS:
            env_values = [os.getenv(f"{provider.upper()}_API_KEY", "")]
            env_values.extend(
                re.split(r"[,\r\n]+", os.getenv(f"{provider.upper()}_API_KEYS", ""))
            )
            pool = self._data["api_keys"].setdefault(provider, [])
            for value in env_values:
                key = value.strip()
                if key and key not in pool:
                    pool.append(key)

    def _normalize(self) -> None:
        """Repair missing/invalid persisted fields without losing valid state."""
        if self._data.get("provider") not in PROVIDERS:
            self._data["provider"] = _DEFAULTS["provider"]
        for field in ("api_keys", "models", "accounts", "languages", "login_flows"):
            if not isinstance(self._data.get(field), dict):
                self._data[field] = {}
        # Migrate legacy provider -> "single key" values to provider -> [keys]
        # and discard malformed/empty entries without exposing their contents.
        normalized_keys: dict[str, list[str]] = {}
        for provider, raw_keys in self._data["api_keys"].items():
            if provider not in PROVIDERS:
                continue
            values = [raw_keys] if isinstance(raw_keys, str) else raw_keys
            if not isinstance(values, list):
                continue
            keys: list[str] = []
            for value in values:
                if isinstance(value, str) and value.strip() and value.strip() not in keys:
                    keys.append(value.strip())
            if keys:
                normalized_keys[provider] = keys
        self._data["api_keys"] = normalized_keys
        chats = self._data.get("chats")
        if not isinstance(chats, list):
            chats = []
        self._data["chats"] = list(dict.fromkeys(
            chat_id for chat_id in chats if isinstance(chat_id, int) and not isinstance(chat_id, bool)
        ))
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(self._data.get("daily_time", ""))):
            self._data["daily_time"] = _DEFAULTS["daily_time"]

    def _save(self) -> None:
        storage.save("config", self._data)

    # -- LLM provider / keys ---------------------------------------------------

    @property
    def provider(self) -> str:
        return self._data["provider"]

    def set_provider(self, provider: str) -> None:
        if provider not in PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        with self._lock:
            self._data["provider"] = provider
            self._save()

    def get_key(self, provider: str) -> str | None:
        """Return the first key (compatibility helper); prefer get_keys()."""
        keys = self.get_keys(provider)
        return keys[0] if keys else None

    def get_keys(self, provider: str) -> list[str]:
        """Return a copy of the ordered key pool for a provider."""
        keys = self._data["api_keys"].get(provider, [])
        return list(keys) if isinstance(keys, list) else []

    def set_key(self, provider: str, key: str) -> bool:
        """Append a unique key to a provider pool; return whether it was added."""
        if provider not in PROVIDERS or not key.strip():
            raise ValueError("A supported provider and non-empty API key are required")
        clean = key.strip()
        with self._lock:
            pool = self._data["api_keys"].setdefault(provider, [])
            if clean in pool:
                return False
            pool.append(clean)
            self._save()
            return True

    def delete_key(self, provider: str) -> bool:
        """Delete every key for a provider (legacy command behavior)."""
        with self._lock:
            removed = self._data["api_keys"].pop(provider, None) is not None
            if removed:
                self._save()
            return removed

    def delete_key_at(self, provider: str, index: int) -> str | None:
        """Delete and return one key by its one-based displayed index."""
        if index < 1:
            return None
        with self._lock:
            pool = self._data["api_keys"].get(provider, [])
            if not isinstance(pool, list) or index > len(pool):
                return None
            removed = pool.pop(index - 1)
            if not pool:
                self._data["api_keys"].pop(provider, None)
            self._save()
            return removed

    def model_for(self, provider: str) -> str:
        return self._data["models"].get(provider) or DEFAULT_MODELS[provider]

    def set_model(self, provider: str, model: str) -> None:
        if provider not in PROVIDERS or not model.strip():
            raise ValueError("A supported provider and non-empty model are required")
        with self._lock:
            self._data["models"][provider] = model.strip()
            self._save()

    # -- Daily digest ------------------------------------------------------------

    @property
    def daily_time(self) -> str:
        return self._data["daily_time"]

    @property
    def last_digest_date(self) -> str:
        value = self._data.get("last_digest_date", "")
        return value if isinstance(value, str) else ""

    def set_daily_time(self, hhmm: str) -> None:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", hhmm):
            raise ValueError("Daily time must use 24-hour HH:MM format")
        with self._lock:
            self._data["daily_time"] = hhmm
            self._save()

    def mark_digest_sent(self, date_str: str) -> None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
            raise ValueError("Digest date must use YYYY-MM-DD format")
        with self._lock:
            self._data["last_digest_date"] = date_str
            self._save()

    @property
    def chats(self) -> list[int]:
        return list(self._data["chats"])

    def add_chat(self, chat_id: int) -> bool:
        with self._lock:
            if chat_id in self._data["chats"]:
                return False
            self._data["chats"].append(chat_id)
            self._save()
            return True

    def remove_chat(self, chat_id: int) -> bool:
        with self._lock:
            if chat_id not in self._data["chats"]:
                return False
            self._data["chats"].remove(chat_id)
            self._save()
            return True

    # -- Interactive /login flow state (persisted so it survives serverless restarts) --

    def get_login_flow(self, chat_id: int) -> dict | None:
        return self._data.setdefault("login_flows", {}).get(str(chat_id))

    def set_login_flow(self, chat_id: int, flow: dict) -> None:
        with self._lock:
            self._data.setdefault("login_flows", {})[str(chat_id)] = flow
            self._save()

    def clear_login_flow(self, chat_id: int) -> None:
        with self._lock:
            if self._data.setdefault("login_flows", {}).pop(str(chat_id), None) is not None:
                self._save()

    # -- Per-chat interface language ---------------------------------------------------

    def get_language(self, chat_id: int) -> str:
        return self._data["languages"].get(str(chat_id), "en")

    def set_language(self, chat_id: int, lang: str) -> None:
        if lang not in ("en", "km"):
            raise ValueError(f"Unsupported language: {lang}")
        with self._lock:
            self._data["languages"][str(chat_id)] = lang
            self._save()

    # -- Per-chat calendar accounts -------------------------------------------------

    def get_account(self, chat_id: int) -> dict | None:
        """Return a copy of this chat's calendar account data, if configured."""
        account = self._data["accounts"].get(str(chat_id))
        return dict(account) if isinstance(account, dict) else None

    @property
    def account_chat_ids(self) -> list[int]:
        """Chat IDs with a persisted calendar account."""
        result: list[int] = []
        for raw_chat_id, account in self._data["accounts"].items():
            if not isinstance(account, dict):
                continue
            try:
                result.append(int(raw_chat_id))
            except (TypeError, ValueError):
                continue
        return result

    def set_account(self, chat_id: int, email: str, token: str) -> None:
        if not email.strip() or not token.strip():
            raise ValueError("A non-empty calendar email and token are required")
        with self._lock:
            # Store the revocable API token, never the user's password. Existing
            # password-based records are migrated by CalendarClient after login.
            self._data["accounts"][str(chat_id)] = {
                "email": email.strip(),
                "token": token.strip(),
            }
            self._save()

    def remove_account(self, chat_id: int) -> bool:
        with self._lock:
            removed = self._data["accounts"].pop(str(chat_id), None) is not None
            if removed:
                self._save()
            return removed


cfg = Config()
