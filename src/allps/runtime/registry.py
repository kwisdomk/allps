"""Runtime registry and selection coordinator for ALLPS inference backends.

Manages provider registration, dynamic discovery, readiness verification, and
safe fallback selection in accordance with governance policies.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Sequence

import httpx

from allps.agent.adapter import (
    DeterministicMockClient,
    GenerationResult,
    InferenceClient,
    InferenceError,
    InferenceUnavailableError,
    LocalOpenAIClient,
)
from allps.runtime.deterministic import DeterministicAnalysisClient
from allps.runtime.discovery import ProviderDiscoveryService
from allps.runtime.models import (
    ExecutionMode,
    ModelDiscoveryResult,
    ModelProbeResult,
    ProviderConfig,
    ProviderType,
    RuntimeSelectionResult,
    RuntimeType,
)

logger = logging.getLogger(__name__)


class RuntimeSelectionError(InferenceUnavailableError):
    """Raised when runtime selection fails to find a valid backend in live mode."""


class ResilientInferenceClient:
    """Inference client wrapper supporting bounded deterministic fallback in AUTO mode.

    Guarantees:
    - In LIVE mode: inference failures are raised immediately; silent fallback is strictly prohibited.
    - In AUTO mode: inference failures trigger deterministic fallback; original error is recorded.
    - Output validation failures are handled downstream and never masked.
    """

    def __init__(
        self,
        primary_client: InferenceClient,
        fallback_client: InferenceClient | None = None,
        allow_fallback: bool = False,
        on_fallback: Callable[[Exception], None] | None = None,
    ) -> None:
        self.primary_client = primary_client
        self.fallback_client = fallback_client
        self.allow_fallback = allow_fallback
        self.on_fallback = on_fallback
        self.last_fallback_error: Exception | None = None
        self.used_fallback: bool = False

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Attempt primary inference; fall back to deterministic client only if explicitly allowed."""
        # Reset per-request provenance state so subsequent successful AI calls are never mislabeled
        self.used_fallback = False
        self.last_fallback_error = None

        try:
            result = await self.primary_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format,
            )
            # Re-ensure flags remain False upon success
            self.used_fallback = False
            self.last_fallback_error = None
            if isinstance(result, GenerationResult):
                return result
            return GenerationResult(
                text=str(result),
                used_fallback=False,
                fallback_error=None,
                runtime_method="live_ai",
            )
        except InferenceError as exc:
            if not self.allow_fallback or self.fallback_client is None:
                raise

            logger.warning(
                "Primary inference failed (%s); engaging bounded deterministic fallback.", exc
            )
            self.last_fallback_error = exc
            self.used_fallback = True
            if self.on_fallback:
                self.on_fallback(exc)

            fb_result = await self.fallback_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                response_format=response_format,
            )
            return GenerationResult(
                text=str(fb_result),
                used_fallback=True,
                fallback_error=exc,
                runtime_method="deterministic_fallback",
            )


class RuntimeRegistry:
    """Configurable registry of inference providers with dynamic discovery and selection."""

    def __init__(
        self,
        providers: Sequence[ProviderConfig] | None = None,
        discovery_service: ProviderDiscoveryService | None = None,
    ) -> None:
        self.discovery_service = discovery_service or ProviderDiscoveryService()
        self._providers: list[ProviderConfig] = list(providers) if providers is not None else self._default_providers()

    @staticmethod
    def _default_providers() -> list[ProviderConfig]:
        probe_timeout = float(os.environ.get("ALLPS_PROBE_TIMEOUT", "15.0"))
        return [
            ProviderConfig(
                name="LM Studio",
                provider_type=ProviderType.LM_STUDIO,
                base_url="http://127.0.0.1:1234/v1",
                preferred_models=[
                    "allps-qwen35-base-4b",
                    "qwen3.5-4b",
                    "qwen2.5-7b-instruct",
                    "mistral-7b-instruct",
                ],
                # Documented provenance: 'allps-qwen35-base-4b' is the local instance identifier
                # for the base 'qwen3.5-4b' model loaded in LM Studio. Distilled variants
                # (e.g. qwen3.5-4b-claude-4.6-opus-reasoning-distilled) are distinct models and
                # are NOT aliased here to prevent silent model substitution.
                model_aliases={
                    "allps-qwen35-base-4b": [
                        "qwen3.5-4b",
                    ],
                    "qwen3.5-4b": [
                        "allps-qwen35-base-4b",
                    ],
                },
                discovery_timeout_seconds=2.0,
                probe_timeout_seconds=probe_timeout,
                inference_timeout_seconds=90.0,
                is_trusted=True,
            ),
            ProviderConfig(
                name="Ollama",
                provider_type=ProviderType.OLLAMA,
                base_url="http://127.0.0.1:11434/v1",
                preferred_models=[
                    "qwen2.5:7b",
                    "mistral:7b",
                    "llama3:8b",
                ],
                discovery_timeout_seconds=2.0,
                probe_timeout_seconds=probe_timeout,
                inference_timeout_seconds=90.0,
                is_trusted=True,
            ),
        ]

    @property
    def providers(self) -> list[ProviderConfig]:
        """Return configured providers."""
        return list(self._providers)

    def set_providers(self, providers: Sequence[ProviderConfig]) -> None:
        """Configure provider list and priorities."""
        self._providers = list(providers)

    def add_provider(self, provider: ProviderConfig, priority: int | None = None) -> None:
        """Add a provider to the registry with optional priority index."""
        if priority is not None:
            self._providers.insert(priority, provider)
        else:
            self._providers.append(provider)

    async def select_runtime(
        self,
        mode: ExecutionMode | str,
        preferred_model: str | None = None,
        custom_endpoint: str | None = None,
        custom_timeout: float | None = None,
        mock_responses: dict[str, str] | None = None,
    ) -> tuple[RuntimeSelectionResult, InferenceClient]:
        """Select and verify an execution runtime according to the requested mode."""
        if isinstance(mode, str):
            mode = ExecutionMode(mode.lower())

        discovery_details: list[dict[str, Any]] = []

        # 1. Mode: MOCK
        if mode == ExecutionMode.MOCK:
            selection = RuntimeSelectionResult(
                execution_mode=ExecutionMode.MOCK,
                runtime_type=RuntimeType.MOCK,
                provider_name="DeterministicMockClient",
                model_id="mock-fixture",
                is_fallback=False,
                discovery_details=[{"status": "mock_mode_selected"}],
            )
            client = DeterministicMockClient(responses=mock_responses)
            return selection, client

        # 2. Mode: DETERMINISTIC
        if mode == ExecutionMode.DETERMINISTIC:
            selection = RuntimeSelectionResult(
                execution_mode=ExecutionMode.DETERMINISTIC,
                runtime_type=RuntimeType.DETERMINISTIC,
                provider_name="DeterministicEngine",
                is_fallback=False,
                discovery_details=[{"status": "explicit_deterministic_selected"}],
            )
            client = DeterministicAnalysisClient()
            return selection, client

        # 3. Build candidate provider list for LIVE or AUTO
        candidate_providers: list[ProviderConfig] = []
        if custom_endpoint:
            # Explicit single endpoint provided
            cand_preferred = [preferred_model] if preferred_model else []
            cand = ProviderConfig(
                name="Custom Endpoint",
                provider_type=ProviderType.CUSTOM,
                base_url=custom_endpoint,
                preferred_models=cand_preferred,
                discovery_timeout_seconds=2.0,
                probe_timeout_seconds=float(os.environ.get("ALLPS_PROBE_TIMEOUT", "15.0")),
                inference_timeout_seconds=custom_timeout or 90.0,
                is_trusted=True,
                is_explicit_selection=bool(preferred_model),
            )
            candidate_providers.append(cand)
        else:
            for p in self._providers:
                if preferred_model:
                    # When a model is explicitly requested, accept strictly that model or its aliases.
                    # Do NOT retain alternative default models (e.g. mistral-7b-instruct).
                    p = ProviderConfig(
                        name=p.name,
                        provider_type=p.provider_type,
                        base_url=p.base_url,
                        preferred_models=[preferred_model],
                        model_aliases=p.model_aliases,
                        discovery_timeout_seconds=p.discovery_timeout_seconds,
                        probe_timeout_seconds=p.probe_timeout_seconds,
                        inference_timeout_seconds=custom_timeout or p.inference_timeout_seconds,
                        is_trusted=p.is_trusted,
                        api_key=p.api_key,
                        is_explicit_selection=True,
                    )
                elif custom_timeout:
                    p = ProviderConfig(
                        name=p.name,
                        provider_type=p.provider_type,
                        base_url=p.base_url,
                        preferred_models=p.preferred_models,
                        model_aliases=p.model_aliases,
                        discovery_timeout_seconds=p.discovery_timeout_seconds,
                        probe_timeout_seconds=p.probe_timeout_seconds,
                        inference_timeout_seconds=custom_timeout,
                        is_trusted=p.is_trusted,
                        api_key=p.api_key,
                    )
                candidate_providers.append(p)

        # 4. Probe candidate providers in priority order
        verified_provider: ProviderConfig | None = None
        verified_model: str | None = None
        probe_latency: float = 0.0

        for provider in candidate_providers:
            # Discovery query
            disc_res: ModelDiscoveryResult = await self.discovery_service.discover_models(provider)
            detail: dict[str, Any] = {
                "provider": provider.name,
                "base_url": provider.base_url,
                "reachable": disc_res.is_reachable,
                "models_found": disc_res.models_found,
                "selected_model": disc_res.selected_model,
                "discovery_error": disc_res.error_message,
            }

            if not disc_res.is_reachable or not disc_res.selected_model:
                discovery_details.append(detail)
                continue

            # Model operational readiness probe (minimal request, no learner data)
            probe_res: ModelProbeResult = await self.discovery_service.probe_model_readiness(
                provider, disc_res.selected_model
            )
            detail["probe_ready"] = probe_res.is_ready
            detail["probe_latency_ms"] = probe_res.latency_ms
            detail["probe_error"] = probe_res.error_message
            discovery_details.append(detail)

            if probe_res.is_ready:
                verified_provider = provider
                verified_model = disc_res.selected_model
                probe_latency = probe_res.latency_ms
                break

        # 5. Evaluate results against mode
        if verified_provider and verified_model:
            selection = RuntimeSelectionResult(
                execution_mode=mode,
                runtime_type=RuntimeType.LIVE_AI,
                provider_name=verified_provider.name,
                model_id=verified_model,
                endpoint=verified_provider.base_url,
                is_fallback=False,
                discovery_details=discovery_details,
            )
            ai_client = LocalOpenAIClient(
                base_url=verified_provider.base_url,
                model=verified_model,
                timeout_seconds=verified_provider.inference_timeout_seconds,
                api_key=verified_provider.api_key,
            )

            # In AUTO mode, wrap with ResilientInferenceClient allowing bounded fallback
            if mode == ExecutionMode.AUTO:
                resilient_client = ResilientInferenceClient(
                    primary_client=ai_client,
                    fallback_client=DeterministicAnalysisClient(),
                    allow_fallback=True,
                )
                return selection, resilient_client

            return selection, ai_client

        # If live mode requested but no working AI provider found: strictly fail
        if mode == ExecutionMode.LIVE:
            err_reasons = [
                f"{d.get('provider')}: {d.get('probe_error') or d.get('discovery_error') or 'no compatible model ready'}"
                for d in discovery_details
            ]
            raise RuntimeSelectionError(
                f"Live AI execution requested, but no verified inference provider is ready. Probed: {err_reasons}"
            )

        # In AUTO mode with no available AI providers: fall back to deterministic
        fallback_reasons = "; ".join(
            f"{d.get('provider')} ({d.get('probe_error') or d.get('discovery_error') or 'unavailable'})"
            for d in discovery_details
        )
        selection = RuntimeSelectionResult(
            execution_mode=ExecutionMode.AUTO,
            runtime_type=RuntimeType.DETERMINISTIC,
            provider_name="DeterministicEngine",
            is_fallback=True,
            fallback_reason=f"AI providers unavailable: {fallback_reasons}",
            discovery_details=discovery_details,
        )
        fallback_client = DeterministicAnalysisClient()
        return selection, fallback_client
