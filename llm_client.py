"""
Thin async wrapper around the Anthropic SDK.
All three agents (tailor, verifier, validator) go through here.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic

import config

log = logging.getLogger("llm")

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = config.ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. "
                "Either set config.ANTHROPIC_API_KEY or export the env var."
            )
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


async def call(
    system: str,
    user: str,
    *,
    expect_json: bool = True,
) -> Any:
    """
    Single async LLM call. Returns parsed dict if expect_json=True, else raw string.
    Strips markdown fences before JSON parsing.
    """
    client = get_client()

    response = await client.messages.create(
        model=config.MODEL,
        max_tokens=config.MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw: str = response.content[0].text.strip()
    log.debug(f"LLM response ({len(raw)} chars)")

    if not expect_json:
        return raw

    return _parse_json(raw)


def _parse_json(raw: str) -> Any:
    """Strip optional markdown fences then parse."""
    text = raw
    if text.startswith("```"):
        lines = text.split("\n")
        # drop first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse failed: {e}\nRaw response:\n{raw[:500]}")
        raise
