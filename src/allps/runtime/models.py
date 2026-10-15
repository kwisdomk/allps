"""Domain models and configuration types for ALLPS runtime discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class ExecutionMode(str, Enum):
    """Supported execution modes for ALLPS pipeline."""

    AUTO = "auto"
    LIVE = "live"
    DETERMINISTIC = "deterministic"
    MOCK = "mock"


class RuntimeType(str, Enum):
    """Types of runtime execution backends."""

    LIVE_AI = "live_ai"
    DETERMINISTIC = "deterministic"
    MOCK = "mock"


class ProviderType(str, Enum):
    """Known inference provider types."""

    LM_STUDIO = "lm_studio"
    OLLAMA = "ollama"
    DETERMINISTIC = "deterministic"
    MOCK = "mock"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for an inference provider."""

    name: str
    provider_type: ProviderType
    base_url: str
    preferred_models: list[str] = field(default_factory=list)
    model_aliases: dict[str, list[str]] = field(default_factory=dict)
    discovery_timeout_seconds: float = 2.0
    probe_timeout_seconds: float = 5.0
    inference_timeout_seconds: float = 60.0
    is_trusted: bool = True
    api_key: str = "not-needed"
    is_explicit_selection: bool = False


@dataclass
class ModelDiscoveryResult:
    """Result of querying /v1/models on a provider."""

    provider_name: str
    is_reachable: bool
    models_found: list[str] = field(default_factory=list)
    selected_model: str | None = None
    error_message: str | None = None


@dataclass
class ModelProbeResult:
    """Result of testing minimal inference readiness with zero learner data."""

    provider_name: str
    model_id: str
    is_ready: bool
    latency_ms: float = 0.0
    error_message: str | None = None


@dataclass
class RuntimeSelectionResult:
    """Final decision regarding runtime backend selection."""

    execution_mode: ExecutionMode
    runtime_type: RuntimeType
    provider_name: str
    model_id: str | None = None
    endpoint: str | None = None
    is_fallback: bool = False
    fallback_reason: str | None = None
    discovery_details: list[dict[str, Any]] = field(default_factory=list)
