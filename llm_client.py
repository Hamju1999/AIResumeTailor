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
import asyncio
import time
from collections import deque
log = logging.getLogger("llm")
_client: anthropic.AsyncAnthropic | None = None
_token_window: deque = deque()  
_TPM_LIMIT = 28_000 

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

def _check_token_budget(estimated_tokens: int) -> float:
    """Returns seconds to wait if budget is near limit, else 0."""
    now = time.monotonic()
    while _token_window and now - _token_window[0][0] > 60:
        _token_window.popleft()
    used = sum(t for _, t in _token_window)
    _token_window.append((now, estimated_tokens))
    if used + estimated_tokens > _TPM_LIMIT:
        wait = 60 - (now - _token_window[0][0]) + 1
        log.info(f"Token budget near limit ({used:,} used) — waiting {wait:.0f}s")
        return max(wait, 1.0)
    return 0.0

async def call(system, user, *, expect_json=True):
    client = get_client()
    estimated = (len(system) + len(user)) // 4
    wait_secs = _check_token_budget(estimated)
    if wait_secs > 0:
        await asyncio.sleep(wait_secs)
    for attempt in range(4):  
        try:
            response = await client.messages.create(
                model=config.MODEL,
                max_tokens=config.MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text.strip()
            log.debug(f"LLM response ({len(raw)} chars)")
            return raw if not expect_json else _parse_json(raw)
        except anthropic.RateLimitError as e:
            wait = 60 * (attempt + 1)  
            log.warning(f"Rate limit hit - waiting {wait}s before retry {attempt+1}/3")
            await asyncio.sleep(wait)
        except anthropic.APIStatusError as e:
            if e.status_code == 529:    # overloaded
                wait = 30 * (attempt + 1)
                log.warning(f"API overloaded (529) - waiting {wait}s")
                await asyncio.sleep(wait)
            else:
                raise   
        except anthropic.APIConnectionError:
            wait = 10 * (attempt + 1)
            log.warning(f"Connection error - waiting {wait}s")
            await asyncio.sleep(wait)
    raise RuntimeError("LLM call failed after 4 attempts (rate limit or overload)")

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
