"""Multi-provider LLM gateway: Google Gemini, Anthropic Claude, OpenAI GPT.

Claude goes through the official `anthropic` SDK; Gemini and OpenAI use their
REST APIs via httpx. All providers are exposed through one coroutine:

    reply = await llm.chat("claude", messages, system="...")

`messages` is a list of {"role": "user" | "assistant", "content": str} in
chronological order, ending with the latest user message.
"""

from __future__ import annotations

import anthropic
import httpx

from config import PROVIDER_LABELS, PROVIDERS, cfg

REQUEST_TIMEOUT = 120.0
MAX_TOKENS = 3000


class LLMError(Exception):
    """A provider call failed; the message is safe to show to the user."""


class LLMNotConfigured(LLMError):
    """No API key stored for the requested provider."""


async def chat(
    provider: str,
    messages: list[dict[str, str]],
    system: str | None = None,
    max_tokens: int = MAX_TOKENS,
) -> str:
    if provider not in PROVIDERS:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}")
    api_key = cfg.get_key(provider)
    if not api_key:
        raise LLMNotConfigured(
            f"No API key configured for {PROVIDER_LABELS[provider]}.\n"
            f"Set one with:  /setkey {provider} <YOUR_API_KEY>"
        )
    model = cfg.model_for(provider)
    if provider == "claude":
        return await _claude(api_key, model, system, messages, max_tokens)
    if provider == "gemini":
        return await _gemini(api_key, model, system, messages, max_tokens)
    return await _openai(api_key, model, system, messages, max_tokens)


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
        raise LLMError("Claude rejected the API key. Update it with /setkey claude <key>") from exc
    except anthropic.NotFoundError as exc:
        raise LLMError(f"Claude model '{model}' not found. Fix it with /setmodel claude <model>") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Claude is rate-limited right now - try again in a moment.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Claude API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach the Claude API (network error).") from exc
    finally:
        await client.close()

    if response.stop_reason == "refusal":
        return "Claude declined to answer this request for safety reasons."
    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return text or "(Claude returned an empty response.)"


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
        raise LLMError("Could not reach the Gemini API (network error).") from exc

    if response.status_code in (401, 403):
        raise LLMError("Gemini rejected the API key. Update it with /setkey gemini <key>")
    if response.status_code == 404:
        raise LLMError(f"Gemini model '{model}' not found. Fix it with /setmodel gemini <model>")
    if response.status_code == 429:
        raise LLMError("Gemini is rate-limited right now - try again in a moment.")
    if response.status_code != 200:
        raise LLMError(f"Gemini API error {response.status_code}: {response.text[:300]}")

    data = response.json()
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
        raise LLMError("Could not reach the OpenAI API (network error).") from exc

    if response.status_code == 401:
        raise LLMError("OpenAI rejected the API key. Update it with /setkey openai <key>")
    if response.status_code == 404:
        raise LLMError(f"OpenAI model '{model}' not found. Fix it with /setmodel openai <model>")
    if response.status_code == 429:
        raise LLMError("OpenAI is rate-limited (or out of quota) - try again later.")
    if response.status_code != 200:
        raise LLMError(f"OpenAI API error {response.status_code}: {response.text[:300]}")

    data = response.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"OpenAI returned an unexpected response: {str(data)[:300]}")
    return text or "(OpenAI returned an empty response.)"
