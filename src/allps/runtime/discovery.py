"""Runtime discovery and readiness probing for inference providers.

Probes /v1/models and verifies inference readiness without transmitting learner data.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from allps.runtime.models import (
    ModelDiscoveryResult,
    ModelProbeResult,
    ProviderConfig,
)

logger = logging.getLogger(__name__)


class ProviderDiscoveryService:
    """Discovers models and verifies operational readiness for OpenAI-compatible providers."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._external_client = client

    async def discover_models(self, config: ProviderConfig) -> ModelDiscoveryResult:
        """Query /v1/models with bounded timeout and match against preferred models."""
        if not config.is_trusted:
            logger.warning("Provider %s is marked untrusted; rejecting discovery.", config.name)
            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=False,
                error_message="Provider is untrusted.",
            )

        endpoint = f"{config.base_url.rstrip('/')}/models"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        }

        try:
            timeout_cfg = httpx.Timeout(
                config.discovery_timeout_seconds,
                connect=min(config.discovery_timeout_seconds, 1.5),
            )
            if self._external_client:
                resp = await asyncio.wait_for(
                    self._external_client.get(
                        endpoint, headers=headers, timeout=timeout_cfg
                    ),
                    timeout=config.discovery_timeout_seconds + 0.5,
                )
                data = resp.json()
            else:
                async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                    resp = await asyncio.wait_for(
                        client.get(endpoint, headers=headers),
                        timeout=config.discovery_timeout_seconds + 0.5,
                    )
                    resp.raise_for_status()
                    data = resp.json()

            if not isinstance(data, dict):
                return ModelDiscoveryResult(
                    provider_name=config.name,
                    is_reachable=False,
                    error_message=f"Malformed response from {endpoint}: expected dict, got {type(data).__name__}",
                )

            # OpenAI /v1/models response schema: {"data": [{"id": "..."}, ...]}
            raw_data = data.get("data", [])
            if not isinstance(raw_data, list):
                return ModelDiscoveryResult(
                    provider_name=config.name,
                    is_reachable=False,
                    error_message=f"Malformed models field 'data': expected list, got {type(raw_data).__name__}",
                )

            models_found: list[str] = []
            for item in raw_data:
                if isinstance(item, dict) and "id" in item:
                    models_found.append(str(item["id"]))
                elif isinstance(item, str):
                    models_found.append(item)

            if not models_found:
                return ModelDiscoveryResult(
                    provider_name=config.name,
                    is_reachable=True,
                    models_found=[],
                    selected_model=None,
                    error_message="No models reported by provider.",
                )

            # Match against configured preferences
            if config.is_explicit_selection:
                selected_model = self._select_explicit_model(
                    models_found, config.preferred_models, config.model_aliases
                )
            else:
                selected_model = self._select_best_matching_model(
                    models_found, config.preferred_models, config.model_aliases
                )

            if config.preferred_models and selected_model is None:
                return ModelDiscoveryResult(
                    provider_name=config.name,
                    is_reachable=True,
                    models_found=models_found,
                    selected_model=None,
                    error_message=f"Requested model preferences {config.preferred_models} not found in available models: {models_found}",
                )

            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=True,
                models_found=models_found,
                selected_model=selected_model,
            )

        except (httpx.ConnectError, httpx.NetworkError) as exc:
            logger.info("Provider %s unreachable: %s", config.name, exc)
            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=False,
                error_message=f"Connection refused or unreachable: {exc}",
            )
        except (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError) as exc:
            logger.info("Provider %s discovery timed out after %.2fs", config.name, config.discovery_timeout_seconds)
            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=False,
                error_message=f"Discovery request timed out after {config.discovery_timeout_seconds}s: {exc}",
            )
        except httpx.HTTPStatusError as exc:
            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=False,
                error_message=f"HTTP status {exc.response.status_code}: {exc.response.text}",
            )
        except Exception as exc:
            logger.warning("Unexpected error during discovery for %s: %s", config.name, exc)
            return ModelDiscoveryResult(
                provider_name=config.name,
                is_reachable=False,
                error_message=f"Discovery failed: {exc}",
            )

    async def probe_model_readiness(
        self,
        config: ProviderConfig,
        model_id: str,
    ) -> ModelProbeResult:
        """Verify readiness of selected model using a minimal inference probe containing no learner data."""
        if not config.is_trusted:
            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=False,
                error_message="Provider is untrusted.",
            )

        endpoint = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        }

        # Minimal probe payload without learner information
        probe_payload: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "temperature": 0.0,
        }

        t0 = time.perf_counter()
        try:
            timeout_cfg = httpx.Timeout(
                config.probe_timeout_seconds,
                connect=min(config.probe_timeout_seconds, 2.0),
            )
            if self._external_client:
                resp = await asyncio.wait_for(
                    self._external_client.post(
                        endpoint, json=probe_payload, headers=headers, timeout=timeout_cfg
                    ),
                    timeout=config.probe_timeout_seconds + 0.5,
                )
                resp.raise_for_status()
                data = resp.json()
            else:
                async with httpx.AsyncClient(timeout=timeout_cfg) as client:
                    resp = await asyncio.wait_for(
                        client.post(endpoint, json=probe_payload, headers=headers),
                        timeout=config.probe_timeout_seconds + 0.5,
                    )
                    resp.raise_for_status()
                    data = resp.json()

            latency_ms = (time.perf_counter() - t0) * 1000

            if not isinstance(data, dict):
                return ModelProbeResult(
                    provider_name=config.name,
                    model_id=model_id,
                    is_ready=False,
                    latency_ms=latency_ms,
                    error_message=f"Malformed probe response: expected dict, got {type(data).__name__}",
                )

            choices = data.get("choices")
            if not isinstance(choices, list) or len(choices) == 0:
                return ModelProbeResult(
                    provider_name=config.name,
                    model_id=model_id,
                    is_ready=False,
                    latency_ms=latency_ms,
                    error_message=f"Model probe returned empty choices: {data}",
                )

            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=True,
                latency_ms=latency_ms,
            )

        except (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError) as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=False,
                latency_ms=latency_ms,
                error_message=f"Inference probe timed out after {config.probe_timeout_seconds}s: {exc}",
            )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=False,
                latency_ms=latency_ms,
                error_message=f"Connection error during probe: {exc}",
            )
        except httpx.HTTPStatusError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=False,
                latency_ms=latency_ms,
                error_message=f"HTTP status {exc.response.status_code} during probe: {exc.response.text}",
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ModelProbeResult(
                provider_name=config.name,
                model_id=model_id,
                is_ready=False,
                latency_ms=latency_ms,
                error_message=f"Probe failed: {exc}",
            )

    @staticmethod
    def _select_explicit_model(
        available_models: list[str],
        preferred_models: list[str],
        model_aliases: dict[str, list[str]] | None = None,
    ) -> str | None:
        """Match explicitly requested models strictly against provider IDs or configured aliases.

        Does NOT strip namespaces (e.g. 'publisher/model'), file extensions, or quantization suffixes.
        Only allows:
        1. Exact match.
        2. Case-insensitive exact match.
        3. Configured alias exact / case-insensitive exact match.
        """
        if not preferred_models:
            return None

        aliases = model_aliases or {}

        for req in preferred_models:
            targets = [req] + aliases.get(req, [])

            # 1. Exact match
            for target in targets:
                for model in available_models:
                    if model == target:
                        return model

            # 2. Case-insensitive exact match
            for target in targets:
                target_lower = target.lower()
                for model in available_models:
                    if model.lower() == target_lower:
                        return model

        return None

    @staticmethod
    def _select_best_matching_model(
        available_models: list[str],
        preferred_models: list[str],
        model_aliases: dict[str, list[str]] | None = None,
    ) -> str | None:
        """Match available models against preferences in order of priority.

        Enforces strict matching hierarchy to prevent unintended model hijacking:
        1. Exact match.
        2. Case-insensitive exact match.
        3. Normalized separator / basename match (canonicalizing separators '-' and ':' and '_',
           and stripping repository/namespace prefixes e.g. 'org/model' -> 'model').
        4. Explicitly configured aliases.

        Unrestricted substring or containment matching is strictly forbidden.
        """
        if not preferred_models:
            return available_models[0] if available_models else None

        aliases = model_aliases or {}

        def normalize_id(name: str) -> str:
            base = name.split("/")[-1].lower()
            if base.endswith(".gguf"):
                base = base[:-5]
            elif base.endswith(".bin"):
                base = base[:-4]
            # Strip standard quantization suffix (e.g. -q4_k_m, -q8_0)
            base = re.sub(r"-q[0-9]+(_[a-z0-9]+)*$", "", base)
            return base.replace(":", "-").replace("_", "-")

        for pref in preferred_models:
            targets = [pref] + aliases.get(pref, [])

            # 1. Exact match
            for target in targets:
                for model in available_models:
                    if model == target:
                        return model

            # 2. Case-insensitive exact match
            for target in targets:
                target_lower = target.lower()
                for model in available_models:
                    if model.lower() == target_lower:
                        return model

            # 3. Normalized separator / basename match
            for target in targets:
                target_norm = normalize_id(target)
                for model in available_models:
                    if normalize_id(model) == target_norm:
                        return model

        return None
