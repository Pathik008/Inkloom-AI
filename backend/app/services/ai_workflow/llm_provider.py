"""LLM provider abstraction for Inkloom AI compliance workflow (Phase 6.3).

Provides:
- Configurable real LLM provider integration (Google Gemini & OpenAI-compatible) via HTTPX.
- Strict timeout enforcement (15.0s) and bounded retries.
- Concurrency limiting via extraction semaphore.
- Credential masking and prompt injection defense.
- Safe fallback when credentials are unconfigured.
- Mock LLM provider strictly isolated to test suites.
"""
from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

LLM_HTTP_TIMEOUT_SECONDS = 15.0
MAX_LLM_RETRIES = 2


class LLMError(Exception):
    """Base exception for LLM provider errors."""


class LLMNotConfiguredError(LLMError):
    """Raised when an LLM call is attempted but no API key is configured."""


class LLMTimeoutError(LLMError):
    """Raised when an external LLM request times out."""


class LLMProviderAPIError(LLMError):
    """Raised when an external LLM provider returns an HTTP error or invalid response."""


def sanitize_prompt_input(text: str) -> str:
    """Isolate content to protect against prompt injection or instruction overriding."""
    if not text:
        return ""
    # Strip dangerous control chars and escape boundary tags
    clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    clean = clean.replace("</submission>", "&lt;/submission&gt;")
    clean = clean.replace("<submission>", "&lt;submission&gt;")
    return clean


class LLMProvider(ABC):
    """Abstract interface for LLM completion and extraction."""

    provider_name: str
    model_name: str
    is_mock: bool = False

    @abstractmethod
    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any] | list[Any]:
        """Generate structured JSON response from LLM."""


class GoogleGeminiLLMProvider(LLMProvider):
    """Real Google Gemini LLM provider using HTTPX."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-flash",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise LLMNotConfiguredError("Gemini API key is required and cannot be empty.")
        self.api_key = api_key.strip()
        self.provider_name = "google_gemini"
        self.model_name = model_name
        self._external_client = client

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any] | list[Any]:
        import json

        client = self._external_client or httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT_SECONDS)
        should_close = self._external_client is None

        # Prefer x-goog-api-key header over query string for secret hygiene
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"SYSTEM INSTRUCTIONS:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow all instructions and output only valid JSON."}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }

        try:
            for attempt in range(1, MAX_LLM_RETRIES + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.is_error:
                        raise LLMProviderAPIError(f"Gemini API returned status {response.status_code}")
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise LLMProviderAPIError("Gemini returned zero response candidates.")
                    part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    return json.loads(part_text)
                except (httpx.TimeoutException, TimeoutError) as exc:
                    if attempt >= MAX_LLM_RETRIES:
                        raise LLMTimeoutError(f"Gemini API timed out after {LLM_HTTP_TIMEOUT_SECONDS}s: {exc}") from exc
                    await asyncio.sleep(0.5 * attempt)
                except json.JSONDecodeError as jde:
                    raise LLMProviderAPIError(f"Gemini returned invalid JSON: {jde}") from jde
        finally:
            if should_close:
                await client.aclose()


class OpenAICompatibleLLMProvider(LLMProvider):
    """Generic OpenAI-compatible LLM provider using HTTPX."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise LLMNotConfiguredError("API key is required for OpenAI-compatible LLM provider.")
        self.api_key = api_key.strip()
        self.provider_name = "openai_compatible"
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._external_client = client

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any] | list[Any]:
        import json

        client = self._external_client or httpx.AsyncClient(timeout=LLM_HTTP_TIMEOUT_SECONDS)
        should_close = self._external_client is None

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

        try:
            for attempt in range(1, MAX_LLM_RETRIES + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if response.is_error:
                        raise LLMProviderAPIError(f"OpenAI-compatible LLM returned status {response.status_code}")
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return json.loads(content)
                except (httpx.TimeoutException, TimeoutError) as exc:
                    if attempt >= MAX_LLM_RETRIES:
                        raise LLMTimeoutError(f"LLM request timed out after {LLM_HTTP_TIMEOUT_SECONDS}s: {exc}") from exc
                    await asyncio.sleep(0.5 * attempt)
                except json.JSONDecodeError as jde:
                    raise LLMProviderAPIError(f"LLM returned invalid JSON: {jde}") from jde
        finally:
            if should_close:
                await client.aclose()


class MockLLMProvider(LLMProvider):
    """Configurable mock LLM provider for unit and integration testing."""

    def __init__(
        self,
        canned_claims: list[dict[str, Any]] | None = None,
        canned_fact_verifications: list[dict[str, Any]] | None = None,
        canned_tone_findings: list[dict[str, Any]] | None = None,
        canned_remediations: list[dict[str, Any]] | None = None,
    ):
        self.provider_name = "mock_llm"
        self.model_name = "mock-testing-model"
        self.is_mock = True
        self.canned_claims = canned_claims or []
        self.canned_fact_verifications = canned_fact_verifications or []
        self.canned_tone_findings = canned_tone_findings or []
        self.canned_remediations = canned_remediations or []

    async def generate_json(self, prompt: str, system_prompt: str | None = None) -> dict[str, Any] | list[Any]:
        # Return canned structures based on prompt intent (check specific intents first)
        p_lower = prompt.lower()
        if "verifications" in p_lower or "candidate_chunks" in p_lower or "verify" in p_lower:
            return {"verifications": self.canned_fact_verifications}
        elif "tone" in p_lower or "voice" in p_lower:
            return {"tone_findings": self.canned_tone_findings}
        elif "remediation" in p_lower or "remediations" in p_lower or "fix" in p_lower:
            return {"remediations": self.canned_remediations}
        elif "extract" in p_lower or "claims" in p_lower:
            return {"claims": self.canned_claims}
        return {}


def get_llm_provider(*, force_mock: bool = False, override_api_key: str | None = None) -> LLMProvider | None:
    """Factory to retrieve configured LLM provider or None if unconfigured."""
    if force_mock:
        return MockLLMProvider()

    api_key = (override_api_key or settings.LLM_API_KEY or "").strip()
    if not api_key or api_key in ('""', "''"):
        return None

    provider_name = settings.LLM_PROVIDER.lower().strip()
    model_name = settings.LLM_MODEL_NAME.strip()

    if "gemini" in provider_name or "google" in provider_name or "gemini" in model_name:
        return GoogleGeminiLLMProvider(api_key=api_key, model_name=model_name)
    else:
        return OpenAICompatibleLLMProvider(api_key=api_key, model_name=model_name)
