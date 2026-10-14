"""LLM client wrapper.

Wraps an OpenAI-compatible chat model (via ``langchain-openai``) and exposes
two small primitives used by the agents:

* :meth:`LLMClient.complete_text` - free-form text completion.
* :meth:`LLMClient.complete_json` - schema-constrained structured output.

The client raises :class:`LLMError` when no API key is configured or when the
provider call fails, so callers can degrade gracefully instead of inventing
data.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_DEFAULT_SYSTEM = (
    "You are a careful, evidence-driven research assistant. "
    "You never fabricate facts, sources, quotations, statistics, or URLs. "
    "When information is uncertain or unavailable you say so explicitly."
)


class LLMError(RuntimeError):
    """Raised when an LLM call cannot be completed."""


class LLMClient:
    """Thin wrapper around a chat model with structured-output support."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self._settings.openai_api_key)

    def _get_model(self):
        if not self._settings.openai_api_key:
            raise LLMError(
                "OPENAI_API_KEY is not configured. Set it in your .env file to "
                "enable the language model."
            )
        if self._model is None:
            try:
                from langchain_openai import ChatOpenAI
            except ImportError as exc:  # pragma: no cover - dependency present
                raise LLMError(f"langchain-openai is not installed: {exc}") from exc

            kwargs = {
                "model": self._settings.openai_model,
                "api_key": self._settings.openai_api_key,
                "temperature": self._settings.openai_temperature,
                "timeout": self._settings.request_timeout_seconds,
                "max_retries": 2,
            }
            if self._settings.openai_base_url:
                kwargs["base_url"] = self._settings.openai_base_url

            try:
                self._model = ChatOpenAI(**kwargs)
            except Exception as exc:
                raise LLMError(f"Failed to initialise chat model: {exc}") from exc
        return self._model

    def complete_text(self, user: str, system: str = _DEFAULT_SYSTEM) -> str:
        """Return a free-form text completion."""
        model = self._get_model()
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as exc:  # pragma: no cover
            raise LLMError(f"langchain-core is not installed: {exc}") from exc

        try:
            response = model.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
        except Exception as exc:
            raise LLMError(f"LLM text completion failed: {exc}") from exc

        content = getattr(response, "content", response)
        if isinstance(content, list):
            # Some providers return a list of content blocks.
            parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    parts.append(str(block["text"]))
                else:
                    parts.append(str(block))
            content = "".join(parts)
        return str(content)

    def complete_json(
        self,
        user: str,
        schema: Type[T],
        system: str = _DEFAULT_SYSTEM,
        max_retries: int = 2,
    ) -> T:
        """Return a structured object conforming to ``schema``.

        Tries the provider's native structured-output mode first, then falls
        back to JSON-mode parsing. Raises :class:`LLMError` on failure.
        """
        model = self._get_model()
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError as exc:  # pragma: no cover
            raise LLMError(f"langchain-core is not installed: {exc}") from exc

        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                structured = model.with_structured_output(schema)
                result = structured.invoke(messages)
                if isinstance(result, schema):
                    return result
                if isinstance(result, dict):
                    return schema.model_validate(result)
            except Exception as exc:  # noqa: BLE001 - want to fall back
                last_error = exc
                logger.debug(
                    "Structured output attempt %s/%s failed for %s: %s",
                    attempt,
                    max_retries,
                    schema.__name__,
                    exc,
                )

            # Fallback: ask for raw JSON and parse it.
            try:
                json_prompt = (
                    user
                    + "\n\nRespond with ONLY a single valid JSON object matching "
                    "this JSON schema (no markdown fences, no commentary):\n"
                    + json.dumps(schema.model_json_schema())
                )
                raw = self.complete_text(json_prompt, system=system)
                parsed = _extract_json(raw)
                return schema.model_validate(parsed)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug(
                    "JSON fallback attempt %s/%s failed for %s: %s",
                    attempt,
                    max_retries,
                    schema.__name__,
                    exc,
                )

        raise LLMError(
            f"LLM structured output failed for {schema.__name__}: {last_error}"
        )


def _extract_json(text: str) -> dict:
    """Extract the first JSON object found in ``text``."""
    if not text:
        raise ValueError("Empty LLM response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    return json.loads(cleaned[start : end + 1])
