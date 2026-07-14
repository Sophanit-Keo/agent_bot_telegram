"""Persistent JSON storage for the bot's runtime state.

Two backends, picked automatically:
  * Local files (config.json / memory.json next to the code) - used when the
    bot runs on your own machine with `python bot.py`.
  * Upstash Redis (REST API) - used when UPSTASH_REDIS_REST_URL and
    UPSTASH_REDIS_REST_TOKEN are set. Required on Vercel, whose serverless
    filesystem is wiped between invocations.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
# Vercel's Upstash marketplace integration names these KV_REST_API_*;
# a manually created Upstash database names them UPSTASH_REDIS_REST_*.
REDIS_URL = (
    os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL") or ""
).rstrip("/")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN") or ""
USE_REDIS = bool(REDIS_URL and REDIS_TOKEN)

_HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"}


def load(name: str) -> dict:
    """Load one named JSON blob ('config', 'memory'); {} when absent/broken."""
    if USE_REDIS:
        try:
            response = httpx.get(f"{REDIS_URL}/get/bot:{name}", headers=_HEADERS, timeout=10)
            response.raise_for_status()
            result = response.json().get("result")
            return json.loads(result) if result else {}
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Redis load of %s failed: %s", name, exc)
            return {}
    path = BASE_DIR / f"{name}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Local load of %s failed: %s", name, exc)
    return {}


def save(name: str, data: dict) -> None:
    if USE_REDIS:
        try:
            response = httpx.post(
                f"{REDIS_URL}/set/bot:{name}",
                headers=_HEADERS,
                content=json.dumps(data, ensure_ascii=False),
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Redis save of %s failed: %s", name, exc)
        return
    path = BASE_DIR / f"{name}.json"
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)  # atomic on the same filesystem
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass  # Some Windows filesystems do not implement POSIX permissions.
    except OSError as exc:
        logger.error("Local save of %s failed: %s", name, exc)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
