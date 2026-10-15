"""Inference adapter interface for the ALLPS AI Intelligence Layer.

Provides:
1. InferenceClient protocol.
2. LocalOpenAIClient: talks to OpenAI-compatible local endpoints (LM Studio, Ollama, vLLM).
3. DeterministicMockClient: offline, zero-dependency client for automated CI testing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


class InferenceError(Exception):
    """Base exception for inference adapter failures."""


class InferenceUnavailableError(InferenceError):
    """Raised when the inference service cannot be reached or is offline."""


class InferenceTimeoutError(InferenceError):
    """Raised when the inference service request times out."""


class GenerationResult(str):
    """String result carrying per-request provenance metadata.

    Subclasses str so that it behaves identically to a normal string in all
    parsing, validation, and JSON decoding contexts, while binding provenance
    directly to the request output without shared mutable state.
    """

    used_fallback: bool
    fallback_error: Exception | None
    runtime_method: str

    def __new__(
        cls,
        text: str,
        used_fallback: bool = False,
        fallback_error: Exception | None = None,
        runtime_method: str = "live_ai",
    ) -> GenerationResult:
        obj = str.__new__(cls, text)
        obj.used_fallback = used_fallback
        obj.fallback_error = fallback_error
        obj.runtime_method = runtime_method
        return obj


@runtime_checkable
class InferenceClient(Protocol):
    """Protocol defining the inference adapter interface."""

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Generate a text response given a user prompt and optional system prompt."""
        ...


class LocalOpenAIClient:
    """Inference client connecting to local OpenAI-compatible endpoints (e.g. LM Studio).

    Defaults to http://localhost:1234/v1.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "local-model",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        api_key: str = "not-needed",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.api_key = api_key

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send chat completion request to the OpenAI-compatible endpoint with retries."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,  # Greedy deterministic decoding for factual consistency and reproducibility
        }
        if response_format:
            payload["response_format"] = response_format

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(endpoint, json=payload, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise InferenceError(f"Empty choices received from inference endpoint: {data}")
                    content = choices[0].get("message", {}).get("content", "")
                    return GenerationResult(
                        text=content,
                        used_fallback=False,
                        fallback_error=None,
                        runtime_method="live_ai",
                    )
            except httpx.TimeoutException as exc:
                last_error = InferenceTimeoutError(
                    f"Inference request timed out after {self.timeout_seconds}s (attempt {attempt + 1}/{self.max_retries + 1})"
                )
                last_error.__cause__ = exc
                logger.warning(str(last_error))
            except httpx.ConnectError as exc:
                last_error = InferenceUnavailableError(
                    f"Could not connect to inference endpoint at {self.base_url}: {exc}"
                )
                last_error.__cause__ = exc
                logger.warning(str(last_error))
            except httpx.HTTPStatusError as exc:
                last_error = InferenceError(
                    f"Inference endpoint returned HTTP {exc.response.status_code}: {exc.response.text}"
                )
                last_error.__cause__ = exc
                logger.warning(str(last_error))
            except Exception as exc:
                last_error = InferenceError(f"Unexpected error during inference: {exc}")
                last_error.__cause__ = exc
                logger.warning(str(last_error))

            if attempt < self.max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))

        if last_error:
            raise last_error
        raise InferenceUnavailableError("Inference failed with unknown error.")


class DeterministicMockClient:
    """Deterministic inference client for offline, zero-dependency automated testing.

    Can be initialized with pre-set responses or configured to respond based on prompt rules.
    """

    def __init__(
        self,
        default_response: str | None = None,
        responses: dict[str, str] | None = None,
        should_timeout: bool = False,
        should_fail_connection: bool = False,
    ) -> None:
        self.default_response = default_response or json.dumps({
            "status": "completed",
            "summary": "Demonstrated consistent progress across academic terms.",
            "findings": [
                {
                    "observation": "Mathematics performance remained stable across terms 1, 2, and 3.",
                    "supporting_evidence_ids": ["ev-1", "ev-2", "ev-3"],
                    "co_occurring_factors": [],
                    "teacher_inquiries": ["Maintain current practice schedule."]
                }
            ],
            "contradictions": [],
            "limitations": []
        })
        self.responses = responses or {}
        self.should_timeout = should_timeout
        self.should_fail_connection = should_fail_connection
        self.history: list[dict[str, Any]] = []

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Return a deterministic canned response or simulate network failures."""
        self.history.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "response_format": response_format,
        })

        if self.should_fail_connection:
            raise InferenceUnavailableError("Mock connection refused: inference service offline.")

        if self.should_timeout:
            raise InferenceTimeoutError("Mock request timed out.")

        # Check prompt keyword matches
        for key, resp in self.responses.items():
            if key in prompt:
                return GenerationResult(
                    text=resp,
                    used_fallback=False,
                    fallback_error=None,
                    runtime_method="mock",
                )

        return GenerationResult(
            text=self.default_response,
            used_fallback=False,
            fallback_error=None,
            runtime_method="mock",
        )
