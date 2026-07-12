"""Async client for the Khmer Calendar API (api-calender-sigma.vercel.app).

Supports multiple accounts at once: each Telegram chat can connect its own
calendar account (/login or /register in the bot); chats without one use the
shared default account from .env. Bearer tokens are kept per account and the
client re-authenticates automatically when the API answers 401.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

import config
from config import cfg


class CalendarError(Exception):
    """Raised when the Calendar API cannot be reached or answers with an error."""


def _error_message(response: httpx.Response) -> str:
    """Best human-readable message from an API error body."""
    try:
        body = response.json()
        if isinstance(body, dict) and body.get("message"):
            return str(body["message"])
    except ValueError:
        pass
    return response.text[:200]


class CalendarClient:
    def __init__(self) -> None:
        self._tokens: dict[str, str] = {}  # account key -> bearer token
        self._login_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=config.CALENDAR_BASE_URL,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        await self._http.aclose()

    # -- Accounts -------------------------------------------------------------------

    def _creds(self, chat_id: int | None) -> tuple[str, str, str]:
        """(token-cache key, email, password) for the account this chat uses.

        Every chat must be signed in (/login or /register); the .env account is
        only used for internal calls with chat_id=None (tests, maintenance).
        """
        if chat_id is None:
            return "default", config.CALENDAR_EMAIL, config.CALENDAR_PASSWORD
        account = cfg.get_account(chat_id)
        if not account:
            raise CalendarError(
                "Not signed in. Use /login <email> <password> or "
                "/register <email> <password> [name] first."
            )
        return str(chat_id), account["email"], account["password"]

    def drop_token(self, chat_id: int | None) -> None:
        """Forget the cached token for a chat (after /login, /logout)."""
        self._tokens.pop("default" if chat_id is None else str(chat_id), None)

    async def login(self, email: str, password: str) -> str:
        """Verify credentials against the API; returns a bearer token."""
        try:
            response = await self._http.post(
                "/auth/login",
                json={
                    "email": email,
                    "password": password,
                    "device_name": "telegram-ai-agent",
                },
            )
        except httpx.HTTPError as exc:
            raise CalendarError(f"Calendar API unreachable: {exc}") from exc
        if response.status_code in (401, 422):
            raise CalendarError(f"Login failed: {_error_message(response)}")
        if response.status_code not in (200, 201):
            raise CalendarError(
                f"Calendar login failed ({response.status_code}): {_error_message(response)}"
            )
        return response.json()["data"]["token"]

    async def register(self, name: str, email: str, password: str) -> str:
        """Create a new calendar account; returns a bearer token."""
        try:
            response = await self._http.post(
                "/auth/register",
                json={
                    "name": name,
                    "email": email,
                    "password": password,
                    "device_name": "telegram-ai-agent",
                },
            )
        except httpx.HTTPError as exc:
            raise CalendarError(f"Calendar API unreachable: {exc}") from exc
        if response.status_code == 422:
            raise CalendarError(f"Registration failed: {_error_message(response)}")
        if response.status_code not in (200, 201):
            raise CalendarError(
                f"Registration failed ({response.status_code}): {_error_message(response)}"
            )
        return response.json()["data"]["token"]

    # -- Core request handling ----------------------------------------------------------

    async def _ensure_token(self, key: str, email: str, password: str) -> str:
        if key not in self._tokens:
            async with self._login_lock:
                if key not in self._tokens:
                    self._tokens[key] = await self.login(email, password)
        return self._tokens[key]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        chat_id: int | None = None,
    ) -> Any:
        key, email, password = self._creds(chat_id)
        if not email or not password:
            raise CalendarError(
                "No calendar account available. Connect one with "
                "/login <email> <password> or create one with /register."
            )
        for attempt in (1, 2):
            token = await self._ensure_token(key, email, password)
            try:
                response = await self._http.request(
                    method,
                    path,
                    params=params,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                raise CalendarError(f"Calendar API unreachable: {exc}") from exc
            if response.status_code == 401 and attempt == 1:
                self._tokens.pop(key, None)  # token expired -> re-login and retry once
                continue
            if response.status_code in (200, 201):
                return response.json().get("data")
            if response.status_code == 204:
                return None
            raise CalendarError(
                f"Calendar API {method} {path} failed "
                f"({response.status_code}): {_error_message(response)}"
            )
        raise CalendarError("Calendar API authentication failed twice")

    # -- Read endpoints ------------------------------------------------------------------

    async def day(self, date_str: str, chat_id: int | None = None) -> dict[str, Any]:
        """Full day view: Khmer calendar fields plus public holidays, Buddhist
        events, and the account's notes, events, holiday events and work shift."""
        return await self._request(
            "GET", "/calendar/day", params={"date": date_str}, chat_id=chat_id
        )

    async def events(
        self, date_from: str, date_to: str, chat_id: int | None = None
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/events", params={"from": date_from, "to": date_to}, chat_id=chat_id
        )

    async def me(self, chat_id: int | None = None) -> dict[str, Any]:
        return await self._request("GET", "/auth/me", chat_id=chat_id)

    # -- Write endpoints (dynamic user input) ------------------------------------------------

    async def create_event(
        self, payload: dict[str, Any], chat_id: int | None = None
    ) -> dict[str, Any]:
        """Create an event, e.g. {"title", "starts_at", "ends_at", "location"}."""
        return await self._request("POST", "/events", body=payload, chat_id=chat_id)

    async def create_note(
        self, date_str: str, text: str, chat_id: int | None = None
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/notes", body={"date": date_str, "text": text}, chat_id=chat_id
        )
