"""Long-term memory for the AI Telegram agent.

Each chat gets its own list of remembered facts, persisted to memory.json
(git-ignored) so they survive bot restarts. Facts get in either explicitly
(/remember command) or automatically, when the LLM marks something worth
keeping with a [REMEMBER: ...] tag in its reply.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "memory.json"
MAX_PER_CHAT = 50


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = {}
        if MEMORY_FILE.exists():
            try:
                stored = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    self._data = stored
            except (OSError, json.JSONDecodeError):
                pass

    def _save(self) -> None:
        MEMORY_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

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
