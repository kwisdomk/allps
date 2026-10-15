"""ALLPS Runtime Decision and Discovery Layer.

Provides modular discovery of inference providers, readiness verification, and
safe deterministic execution fallbacks.
"""

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
from allps.runtime.registry import (
    ResilientInferenceClient,
    RuntimeRegistry,
    RuntimeSelectionError,
)

__all__ = [
    "DeterministicAnalysisClient",
    "ExecutionMode",
    "ModelDiscoveryResult",
    "ModelProbeResult",
    "ProviderConfig",
    "ProviderDiscoveryService",
    "ProviderType",
    "ResilientInferenceClient",
    "RuntimeRegistry",
    "RuntimeSelectionError",
    "RuntimeSelectionResult",
    "RuntimeType",
]
