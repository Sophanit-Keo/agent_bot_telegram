"""Vercel entrypoint (ASGI): serves the Telegram webhook and the daily cron.

Vercel's Python runtime looks for an `app` in app.py and routes every request
to it, so this one file handles both paths:

  POST /api/webhook  - Telegram pushes updates here (set via setWebhook)
  GET  /api/cron     - Vercel Cron triggers the daily digest (vercel.json)

The PTB application is cached at module level so warm invocations reuse it.
Local polling mode (`python bot.py`) is unaffected.
"""

from __future__ import annotations

import json
import logging
import os

from telegram import Update

import bot

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vercel")

_app = None


async def _get_app():
    global _app
    if _app is None:
        _app = bot.build_application(for_polling=False)
        await _app.initialize()
    return _app


async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            return body


def _header(scope, name: str) -> str:
    target = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode()
    return ""


async def _respond(send, status: int, text: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": text.encode()})


async def app(scope, receive, send):
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return

    path = scope.get("path", "").rstrip("/")
    method = scope.get("method", "GET").upper()

    if path == "/api/webhook" and method == "POST":
        # Always answer 200 so Telegram won't retry-storm on our errors.
        try:
            data = json.loads(await _read_body(receive) or b"{}")
            application = await _get_app()
            await application.process_update(Update.de_json(data, application.bot))
        except Exception:
            log.exception("webhook error")
        await _respond(send, 200, "ok")
        return

    if path == "/api/cron" and method == "GET":
        secret = os.getenv("CRON_SECRET", "")
        if secret and _header(scope, "authorization") != f"Bearer {secret}":
            await _respond(send, 401, "unauthorized")
            return
        try:
            application = await _get_app()
            await bot._broadcast_digest(application)
            await _respond(send, 200, "digest sent")
        except Exception:
            log.exception("cron error")
            await _respond(send, 200, "digest failed - see logs")
        return

    await _respond(send, 200, "AI Telegram Agent is alive")
