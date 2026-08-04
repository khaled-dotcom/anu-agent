"""Thin wrapper over Groq's OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from .config import settings

ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class GroqError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.groq_api_key:
        raise GroqError("GROQ_API_KEY غير مضبوط. راجع ملف .env")
    return {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }


def _payload(messages: list[dict], stream: bool) -> dict:
    return {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": 0.2,       # factual answers, not creative ones
        "max_tokens": 700,
        "top_p": 0.9,
        "stream": stream,
    }


async def complete(messages: list[dict], timeout: float = 30.0) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            ENDPOINT, headers=_headers(), json=_payload(messages, stream=False)
        )
        if response.status_code != 200:
            raise GroqError(f"Groq {response.status_code}: {response.text[:300]}")
        data = response.json()
        return data["choices"][0]["message"]["content"]


async def stream(messages: list[dict], timeout: float = 60.0) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", ENDPOINT, headers=_headers(), json=_payload(messages, stream=True)
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise GroqError(f"Groq {response.status_code}: {body[:300]!r}")
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"]
                except (KeyError, IndexError, json.JSONDecodeError):
                    continue
                token = delta.get("content")
                if token:
                    yield token
