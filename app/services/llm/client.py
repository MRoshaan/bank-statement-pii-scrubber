from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError

from app.config import settings
from app.services.scrubber.engine import scrub_text
from app.services.scrubber.residual import scan_residual


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class LLMPrivacyError(LLMError):
    pass


def ensure_safe_prompt(system: str, user: str) -> None:
    """Check the complete assembled request, including retries and history."""
    for text in (system, user):
        hits = scan_residual(text)
        if hits:
            types = ", ".join(sorted({str(hit["entity_type"]) for hit in hits}))
            raise LLMPrivacyError(f"Residual PII detected in LLM request: {types}")


def sanitize_model_data(value: Any) -> Any:
    """Scrub every model-controlled string before validation or persistence."""
    if isinstance(value, str):
        result = scrub_text(value)
        if result.residual:
            raise LLMPrivacyError("Model output contains an identifier after scrubbing.")
        return result.text
    if isinstance(value, list):
        return [sanitize_model_data(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_model_data(key): sanitize_model_data(item) for key, item in value.items()}
    return value


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    usage: dict[str, Any]


class GroqLLM:
    def __init__(self) -> None:
        if not settings.groq_api_key:
            raise LLMNotConfigured("GROQ_API_KEY is not configured.")
        self.client = Groq(api_key=settings.groq_api_key, timeout=settings.llm_timeout_seconds, max_retries=0)

    def _call(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        ensure_safe_prompt(system, user)
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
        if not response.choices:
            raise LLMError("Model returned no choices.")
        content = response.choices[0].message.content or ""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise LLMError("Model returned JSON that was not an object.")
        usage = response.usage.model_dump() if hasattr(response.usage, "model_dump") else dict(response.usage or {})
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
                except LLMPrivacyError:
                    raise
                except LLMError as exc:
                    last_error = exc
                    if attempt == 0:
                        # One repair attempt for malformed JSON.
                        user = user + "\n\nYour previous response was not valid JSON. Return one JSON object only."
                        continue
                    break
        # Provider exception bodies can contain credentials or echoed input.
        status = getattr(last_error, "status_code", None)
        detail = f"HTTP {status}" if status else type(last_error).__name__
        raise LLMError(f"Groq request failed after retries ({detail}).") from last_error
