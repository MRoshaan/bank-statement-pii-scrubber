from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError

from app.config import settings


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    usage: dict[str, Any]


class GroqLLM:
    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise LLMNotConfigured("GROQ_API_KEY is not configured.")
        self.client = Groq(api_key=settings.groq_api_key, timeout=settings.llm_timeout_seconds)

    def _call(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            reasoning_effort="low",
        )
        content = response.choices[0].message.content or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {exc}") from exc
        usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage)
        return LLMResult(data=data, model=model, usage=usage)

    def complete_json(
        self,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        models = [settings.groq_model]
        if settings.groq_fallback_model and settings.groq_fallback_model != settings.groq_model:
            models.append(settings.groq_fallback_model)

        last_error: Exception | None = None
        for model in models:
            for attempt in range(3):
                try:
                    return self._call(
                        model=model,
                        system=system,
                        user=user,
                        max_tokens=max_tokens or settings.llm_max_tokens,
                        temperature=settings.llm_temperature if temperature is None else temperature,
                    )
                except RateLimitError as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    break
                except (APIConnectionError, APITimeoutError) as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    break
                except APIStatusError as exc:
                    last_error = exc
                    if exc.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    break
                except LLMError as exc:
                    last_error = exc
                    if attempt == 0:
                        # One repair attempt for malformed JSON.
                        user = user + "\n\nYour previous response was not valid JSON. Return one JSON object only."
                        continue
                    break
        raise LLMError(f"Groq request failed after retries: {last_error}")
