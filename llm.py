"""Multi-provider LLM gateway: Google Gemini, Anthropic Claude, OpenAI GPT,
and Claude via the Anajak proxy.

Claude goes through the official `anthropic` SDK. Anajak (ANAJAK_BASE_URL in
config.py) takes an Anthropic-shaped request body at POST /v1/messages but
replies with an OpenAI-shaped chat-completion body, so it gets its own REST
call via httpx rather than reusing the anthropic SDK's response parsing.
Gemini and OpenAI also use their REST APIs via httpx. All providers are
exposed through one coroutine:

    reply = await llm.chat("claude", messages, system="...")

`messages` is a list of {"role": "user" | "assistant", "content": str} in
chronological order, ending with the latest user message.
"""

from __future__ import annotations

import logging

import anthropic
import httpx

from config import ANAJAK_BASE_URL, PROVIDER_LABELS, PROVIDERS, cfg

REQUEST_TIMEOUT = 120.0
MAX_TOKENS = 3000
logger = logging.getLogger(__name__)

# Last successful key per provider. A failed preferred key is moved behind the
# next key for future requests. Values never leave this process or appear in logs.
_preferred_keys: dict[str, str] = {}


class LLMError(Exception):
    """A provider call failed; the message is safe to show to the user."""


class LLMNotConfigured(LLMError):
    """No API key stored for the requested provider."""


class LLMKeyUnavailable(LLMError):
    """This key cannot serve the request; another key may succeed."""


async def chat(
    provider: str,
    messages: list[dict[str, str]],
    system: str | None = None,
    max_tokens: int = MAX_TOKENS,
) -> str:
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
    api_keys = cfg.get_keys(provider)
    if not api_keys:
        raise LLMNotConfigured(
            f"No API keys configured for {PROVIDER_LABELS[provider]}.\n"
            f"Add one with:  /setkey {provider} <YOUR_API_KEY>"
        )
    model = cfg.model_for(provider)
    preferred = _preferred_keys.get(provider)
    if preferred in api_keys:
        start = api_keys.index(preferred)
        api_keys = api_keys[start:] + api_keys[:start]

    last_error: LLMKeyUnavailable | None = None
    for position, api_key in enumerate(api_keys, start=1):
        try:
            if provider == "claude":
                answer = await _claude(api_key, model, system, messages, max_tokens)
            elif provider == "anajak":
                answer = await _anajak(api_key, model, system, messages, max_tokens)
            elif provider == "gemini":
                answer = await _gemini(api_key, model, system, messages, max_tokens)
            else:
                answer = await _openai(api_key, model, system, messages, max_tokens)
        except LLMKeyUnavailable as exc:
            last_error = exc
            if position < len(api_keys):
                logger.warning(
                    "%s key %d/%d failed (%s); trying the next key",
                    PROVIDER_LABELS[provider],
                    position,
                    len(api_keys),
                    exc,
                )
            continue
        except LLMError:
            raise
        except Exception as exc:  # unexpected provider/network/parsing failure
            last_error = LLMKeyUnavailable(f"unexpected error: {exc}")
            logger.warning(
                "%s key %d/%d raised an unexpected error (%s); trying the next key",
                PROVIDER_LABELS[provider],
                position,
                len(api_keys),
                exc,
                exc_info=True,
            )
            continue
        _preferred_keys[provider] = api_key
        return answer

    _preferred_keys.pop(provider, None)
    detail = str(last_error) if last_error else "unknown provider error"
    raise LLMError(
        f"All {len(api_keys)} configured {PROVIDER_LABELS[provider]} API key(s) "
        f"failed. Last error: {detail}"
    )


# -- Anthropic Claude (official SDK) --------------------------------------------


async def _claude(
    api_key: str,
    model: str,
    system: str | None,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=REQUEST_TIMEOUT)
    try:
        kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
        if system:
            kwargs["system"] = system
        response = await client.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMKeyUnavailable("Claude rejected an API key.") from exc
    except anthropic.NotFoundError as exc:
        raise LLMError(f"Claude model '{model}' not found. Fix it with /setmodel claude <model>") from exc
    except anthropic.RateLimitError as exc:
        raise LLMKeyUnavailable("Claude rate limit or quota reached.") from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code in (401, 403, 408, 409, 429) or exc.status_code >= 500:
            raise LLMKeyUnavailable(
                f"Claude API temporary/key error {exc.status_code}: {exc.message}"
            ) from exc
        raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMKeyUnavailable("Could not reach the Claude API (network error).") from exc
    finally:
        await client.close()

    if response.stop_reason == "refusal":
        return "Claude declined to answer this request for safety reasons."
    if not response.content:
        raise LLMKeyUnavailable(f"Claude returned no content (stop_reason={response.stop_reason}).")
    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return text or "(Claude returned an empty response.)"


# -- Claude via the Anajak proxy (REST) --------------------------------------------
# Anthropic-shaped request body at POST /v1/messages, but an OpenAI-shaped
# chat-completion response - so this parses like _openai() rather than
# reusing the anthropic SDK's (Anthropic-shaped) response parsing.


async def _anajak(
    api_key: str,
    model: str,
    system: str | None,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    # This proxy is hard-wired with its own Claude Code system prompt and
    # ignores/deprioritizes a client-supplied system message (both as a
    # "system"-role message and as a top-level "system" field - confirmed by
    # direct testing). Folding the instructions into the latest user turn is
    # the only way that reliably steers its behavior.
    if system and messages:
        last = messages[-1]
        chat_messages = messages[:-1] + [
            {**last, "content": f"{system}\n\n{last['content']}"}
        ]
    elif system:
        chat_messages = [{"role": "user", "content": system}]
    else:
        chat_messages = messages
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
            response = await http.post(
                f"{ANAJAK_BASE_URL}/v1/messages",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "max_tokens": max_tokens, "messages": chat_messages},
            )
    except httpx.HTTPError as exc:
        raise LLMKeyUnavailable("Could not reach the Anajak API (network error).") from exc

    if response.status_code in (401, 403):
        raise LLMKeyUnavailable("Anajak rejected an API key.")
    if response.status_code == 404:
        raise LLMError(f"Anajak model '{model}' not found. Fix it with /setmodel anajak <model>")
    if response.status_code == 429:
        raise LLMKeyUnavailable("Anajak rate limit or quota reached.")
    if response.status_code in (408, 409) or response.status_code >= 500:
        raise LLMKeyUnavailable(
            f"Anajak API temporary error {response.status_code}: {response.text[:300]}"
        )
    if response.status_code != 200:
        raise LLMError(f"Anajak API error {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except ValueError:
        raise LLMKeyUnavailable(f"Anajak returned a non-JSON response: {response.text[:300]}")
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"Anajak returned an unexpected response: {str(data)[:300]}")
    return text or "(Anajak returned an empty response.)"


# -- Google Gemini (REST) ---------------------------------------------------------


async def _gemini(
    api_key: str,
    model: str,
    system: str | None,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    contents = [
        {
            "role": "user" if message["role"] == "user" else "model",
            "parts": [{"text": message["content"]}],
        }
        for message in messages
    ]
    body: dict = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
            response = await http.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise LLMKeyUnavailable("Could not reach the Gemini API (network error).") from exc

    if response.status_code in (401, 403):
        raise LLMKeyUnavailable("Gemini rejected an API key.")
    if response.status_code == 404:
        raise LLMError(f"Gemini model '{model}' not found. Fix it with /setmodel gemini <model>")
    if response.status_code == 429:
        raise LLMKeyUnavailable("Gemini rate limit or quota reached.")
    if response.status_code in (408, 409) or response.status_code >= 500:
        raise LLMKeyUnavailable(
            f"Gemini API temporary error {response.status_code}: {response.text[:300]}"
        )
    if response.status_code == 400 and any(
        marker in response.text.lower()
        for marker in ("api_key_invalid", "api key not valid", "invalid api key")
    ):
        raise LLMKeyUnavailable("Gemini rejected an API key.")
    if response.status_code != 200:
        raise LLMError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except ValueError:
        raise LLMKeyUnavailable(f"Gemini returned a non-JSON response: {response.text[:300]}")
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, TypeError):
        block_reason = (data.get("promptFeedback") or {}).get("blockReason")
        if block_reason:
            return f"Gemini blocked this request ({block_reason})."
        raise LLMError(f"Gemini returned an unexpected response: {str(data)[:300]}")
    return text or "(Gemini returned an empty response.)"


# -- OpenAI GPT (REST) --------------------------------------------------------------


async def _openai(
    api_key: str,
    model: str,
    system: str | None,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> str:
    chat_messages = ([{"role": "system", "content": system}] if system else []) + messages
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
            response = await http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": chat_messages,
                    "max_completion_tokens": max_tokens,
                },
            )
    except httpx.HTTPError as exc:
        raise LLMKeyUnavailable("Could not reach the OpenAI API (network error).") from exc

    if response.status_code in (401, 403):
        raise LLMKeyUnavailable("OpenAI rejected an API key.")
    if response.status_code == 404:
        raise LLMError(f"OpenAI model '{model}' not found. Fix it with /setmodel openai <model>")
    if response.status_code == 429:
        raise LLMKeyUnavailable("OpenAI rate limit or quota reached.")
    if response.status_code in (408, 409) or response.status_code >= 500:
        raise LLMKeyUnavailable(
            f"OpenAI API temporary error {response.status_code}: {response.text[:300]}"
        )
    if response.status_code != 200:
        raise LLMError(f"OpenAI API error {response.status_code}: {response.text[:300]}")

    try:
        data = response.json()
    except ValueError:
        raise LLMKeyUnavailable(f"OpenAI returned a non-JSON response: {response.text[:300]}")
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"OpenAI returned an unexpected response: {str(data)[:300]}")
    return text or "(OpenAI returned an empty response.)"
