"""Long-term memory for the AI Telegram agent.

Each chat gets its own list of remembered facts, persisted to memory.json
(git-ignored) so they survive bot restarts. Facts get in either explicitly
(/remember command) or automatically, when the LLM marks something worth
keeping with a [REMEMBER: ...] tag in its reply.
"""

from __future__ import annotations

import threading
from datetime import datetime

import storage

MAX_PER_CHAT = 50


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = storage.load("memory")

    def _save(self) -> None:
        storage.save("memory", self._data)

    def list(self, chat_id: int) -> list[str]:
        return [item["text"] for item in self._data.get(str(chat_id), [])]

    def add(self, chat_id: int, text: str) -> bool:
        """Store one fact; returns False for duplicates/empty text."""
        text = " ".join(text.split()).strip()
        if not text:
            return False
        with self._lock:
            items = self._data.setdefault(str(chat_id), [])
            if any(item["text"].lower() == text.lower() for item in items):
                return False
            items.append({"text": text, "saved_at": datetime.now().isoformat(timespec="seconds")})
            del items[:-MAX_PER_CHAT]  # keep only the newest MAX_PER_CHAT facts
            self._save()
            return True

    def forget(self, chat_id: int, index: int) -> str | None:
        """Delete fact by 1-based index; returns the removed text."""
        with self._lock:
            items = self._data.get(str(chat_id), [])
            if not 1 <= index <= len(items):
                return None
            removed = items.pop(index - 1)
            self._save()
            return removed["text"]

    def clear(self, chat_id: int) -> int:
        with self._lock:
            items = self._data.pop(str(chat_id), [])
            if items:
                self._save()
            return len(items)


memories = MemoryStore()
