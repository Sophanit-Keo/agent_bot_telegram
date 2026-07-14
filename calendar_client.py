"""Async client for the Khmer Calendar API (api-calender-sigma.vercel.app).

Supports multiple accounts at once: each Telegram chat can connect its own
calendar account (/login or /register in the bot). Revocable bearer tokens are
stored instead of user passwords. Legacy password records are migrated once.
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
    return response.text[:200] or "empty response"


def _response_data(response: httpx.Response, operation: str) -> Any:
    """Decode the API envelope and turn malformed success bodies into errors."""
    try:
        body = response.json()
    except ValueError as exc:
        raise CalendarError(f"Calendar API returned invalid JSON during {operation}") from exc
    if not isinstance(body, dict) or "data" not in body:
        raise CalendarError(f"Calendar API returned an unexpected response during {operation}")
    return body["data"]


def _response_token(response: httpx.Response, operation: str) -> str:
    data = _response_data(response, operation)
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise CalendarError(f"Calendar API did not return an access token during {operation}")
    return token


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

    def _creds(self, chat_id: int | None) -> tuple[str, str, str, str]:
        """Return (cache key, email, password, saved token).

        Every chat must be signed in (/login or /register); the .env account is
        only used for internal calls with chat_id=None (tests, maintenance).
        """
        if chat_id is None:
            return "default", config.CALENDAR_EMAIL, config.CALENDAR_PASSWORD, ""
        account = cfg.get_account(chat_id)
        if not account:
            raise CalendarError(
                "Not signed in. Use /login <email> <password> or "
                "/register <email> <password> [name] first."
            )
        return (
            str(chat_id),
            str(account.get("email") or ""),
            str(account.get("password") or ""),  # legacy records only
            str(account.get("token") or ""),
        )

    def drop_token(self, chat_id: int | None) -> None:
        """Forget the cached token for a chat (after /login, /logout)."""
        self._tokens.pop("default" if chat_id is None else str(chat_id), None)

    def set_token(self, chat_id: int, token: str) -> None:
        """Cache a token just obtained by /login or /register."""
        self._tokens[str(chat_id)] = token

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
        return _response_token(response, "login")

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
        return _response_token(response, "registration")

    # -- Core request handling ----------------------------------------------------------

    async def _ensure_token(
        self, key: str, email: str, password: str, saved_token: str
    ) -> str:
        if key not in self._tokens:
            async with self._login_lock:
                if key not in self._tokens:
                    if saved_token:
                        self._tokens[key] = saved_token
                    elif email and password:
                        self._tokens[key] = await self.login(email, password)
                    else:
                        raise CalendarError("Calendar session is missing. Please use /login again.")
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
        key, email, password, saved_token = self._creds(chat_id)
        if not saved_token and (not email or not password):
            raise CalendarError(
                "No calendar account available. Connect one with "
                "/login <email> <password> or create one with /register."
            )
        for attempt in (1, 2):
            token = await self._ensure_token(key, email, password, saved_token)
            if chat_id is not None and not saved_token and email and password:
                # A legacy record has just been authenticated. Replace its
                # plaintext password immediately, without waiting for a 401.
                cfg.set_account(chat_id, email, token)
                saved_token, password = token, ""
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
                self._tokens.pop(key, None)
                if email and password:
                    # Migrate old plaintext-password records to token-only state.
                    token = await self.login(email, password)
                    self._tokens[key] = token
                    if chat_id is not None:
                        cfg.set_account(chat_id, email, token)
                    saved_token = token
                    continue
                raise CalendarError("Calendar session expired. Please use /login again.")
            if response.status_code in (200, 201):
                return _response_data(response, f"{method} {path}")
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
        result = await self._request(
            "GET", "/calendar/day", params={"date": date_str}, chat_id=chat_id
        )
        if not isinstance(result, dict):
            raise CalendarError("Calendar API returned invalid day data")
        return result

    async def events(
        self, date_from: str, date_to: str, chat_id: int | None = None
    ) -> list[dict[str, Any]]:
        result = await self._request(
            "GET", "/events", params={"from": date_from, "to": date_to}, chat_id=chat_id
        )
        if not isinstance(result, list):
            raise CalendarError("Calendar API returned invalid event data")
        return [item for item in result if isinstance(item, dict)]

    async def me(self, chat_id: int | None = None) -> dict[str, Any]:
        result = await self._request("GET", "/auth/me", chat_id=chat_id)
        return result if isinstance(result, dict) else {}

    async def work_days(
        self, date_from: str, date_to: str, chat_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Materialized work schedule for a date range: one entry per day with
        shift_template (None = day off), starts_at/ends_at, blocked."""
        result = await self._request(
            "GET",
            "/work-schedule/days",
            params={"from": date_from, "to": date_to},
            chat_id=chat_id,
        )
        if result is None:
            return []
        if not isinstance(result, list):
            raise CalendarError("Calendar API returned invalid work-schedule data")
        return [item for item in result if isinstance(item, dict)]

    # -- Write endpoints (dynamic user input) ------------------------------------------------

    async def create_event(
        self, payload: dict[str, Any], chat_id: int | None = None
    ) -> dict[str, Any]:
        """Create an event, e.g. {"title", "starts_at", "ends_at", "location"}."""
        result = await self._request("POST", "/events", body=payload, chat_id=chat_id)
        if not isinstance(result, dict):
            raise CalendarError("Calendar API returned invalid created-event data")
        return result

    async def create_note(
        self, date_str: str, text: str, chat_id: int | None = None
    ) -> dict[str, Any]:
        result = await self._request(
            "POST", "/notes", body={"date": date_str, "text": text}, chat_id=chat_id
        )
        if not isinstance(result, dict):
            raise CalendarError("Calendar API returned invalid created-note data")
        return result
