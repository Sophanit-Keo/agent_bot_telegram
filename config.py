"""Configuration for the AI Telegram agent.

Secrets and bootstrap values come from .env; runtime state that the bot
manages itself (API keys set via /setkey, chosen provider, subscribed chats,
daily send time) is persisted to config.json next to this file.
"""

from __future__ import annotations

import json
import os
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

PROVIDERS = ("gemini", "claude", "openai")

PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
    "openai": "OpenAI GPT",
}

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash",
    "claude": "claude-opus-4-8",
    "openai": "gpt-4o-mini",
}

_DEFAULTS = {
    "provider": "claude",   # active LLM provider for chat + planning
    "api_keys": {},          # provider -> API key
    "models": {},            # provider -> model id override
    "daily_time": "06:30",   # HH:MM local time for the automatic daily digest
    "chats": [],             # Telegram chat ids subscribed to the daily digest
    "accounts": {},          # chat_id (str) -> personal calendar account {email, password}
    "languages": {},         # chat_id (str) -> interface language: "en" | "km"
}


class Config:
    """Thread-safe runtime configuration persisted to config.json."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data = json.loads(json.dumps(_DEFAULTS))  # deep copy
        self._data.update(storage.load("config"))
        # Seed API keys from the environment the first time they appear.
        for provider in PROVIDERS:
            env_key = os.getenv(f"{provider.upper()}_API_KEY", "").strip()
            if env_key and provider not in self._data["api_keys"]:
                self._data["api_keys"][provider] = env_key

    def _save(self) -> None:
        storage.save("config", self._data)

    # -- LLM provider / keys ---------------------------------------------------

    @property
    def provider(self) -> str:
        return self._data["provider"]

    def set_provider(self, provider: str) -> None:
        with self._lock:
            self._data["provider"] = provider
            self._save()

    def get_key(self, provider: str) -> str | None:
        return self._data["api_keys"].get(provider)

    def set_key(self, provider: str, key: str) -> None:
        with self._lock:
            self._data["api_keys"][provider] = key
            self._save()

    def delete_key(self, provider: str) -> bool:
        with self._lock:
            removed = self._data["api_keys"].pop(provider, None) is not None
            if removed:
                self._save()
            return removed

    def model_for(self, provider: str) -> str:
        return self._data["models"].get(provider) or DEFAULT_MODELS[provider]

    def set_model(self, provider: str, model: str) -> None:
        with self._lock:
            self._data["models"][provider] = model
            self._save()

    # -- Daily digest ------------------------------------------------------------

    @property
    def daily_time(self) -> str:
        return self._data["daily_time"]

    def set_daily_time(self, hhmm: str) -> None:
        with self._lock:
            self._data["daily_time"] = hhmm
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
        with self._lock:
            self._data["languages"][str(chat_id)] = lang
            self._save()

    # -- Per-chat calendar accounts -------------------------------------------------

    def get_account(self, chat_id: int) -> dict | None:
        """Personal calendar account for this chat, or None (shared default)."""
        return self._data["accounts"].get(str(chat_id))

    def set_account(self, chat_id: int, email: str, password: str) -> None:
        with self._lock:
            self._data["accounts"][str(chat_id)] = {"email": email, "password": password}
            self._save()

    def remove_account(self, chat_id: int) -> bool:
        with self._lock:
            removed = self._data["accounts"].pop(str(chat_id), None) is not None
            if removed:
                self._save()
            return removed


cfg = Config()
