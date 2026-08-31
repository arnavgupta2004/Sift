"""Single chokepoint for every LLM API call in this system.

Every LLM call in the agent (query understanding, complexity-classification fallback,
explanation generation) and in the synthetic data generator goes through this module.
That is deliberate: the router's latency/compute claims ("fast route makes zero LLM
calls") are only honest if there is exactly one place an LLM call could originate from,
and it is easy to audit.

Backend: Google Gemini (project originally specced against the Claude API, switched to
Gemini because that's the credential available for this build). The call surface
(`complete`, `is_available`) is intentionally provider-agnostic so swapping backends
again later only touches this file.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_RATE_LIMIT_RETRIES = 3
_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")


@dataclass
class LLMCallResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient:
    """Thin wrapper around the Gemini SDK. No-ops gracefully when no API key is set,
    so the rest of the system can check `client.is_available` and fall back rather than
    crash — this keeps the repo runnable end-to-end without a credential."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._client = None
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.is_available = bool(api_key)
        if self.is_available:
            from google import genai

            self._client = genai.Client(api_key=api_key)

    def complete(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 1.0,
    ) -> LLMCallResult:
        if not self.is_available or self._client is None:
            raise RuntimeError(
                "LLMClient.complete() called without GEMINI_API_KEY set. "
                "Check client.is_available before calling, or set the env var."
            )
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        attempt = 0
        while True:
            try:
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                break
            except errors.ClientError as e:
                # Free-tier quota (429 RESOURCE_EXHAUSTED) is routine, not exceptional,
                # on the model this project runs against — retry with the delay the API
                # itself suggests rather than failing the whole call (and, upstream, the
                # whole route()/explain() step) on a transient rate limit.
                if getattr(e, "code", None) != 429 or attempt >= MAX_RATE_LIMIT_RETRIES:
                    raise
                delay = _extract_retry_delay(str(e))
                attempt += 1
                time.sleep(delay)

        text = response.text or ""
        usage = response.usage_metadata
        return LLMCallResult(
            text=text,
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            model=self.model,
        )


def _extract_retry_delay(error_text: str, default: float = 15.0) -> float:
    match = _RETRY_DELAY_RE.search(error_text)
    return float(match.group(1)) + 1.0 if match else default


@lru_cache(maxsize=1)
def get_client() -> LLMClient:
    return LLMClient()
