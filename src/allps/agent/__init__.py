"""ALLPS AI Intelligence & Bounded Agent Orchestration Layer.

Exports domain contracts, inference adapters, deterministic validators,
and the AgentOrchestrator pipeline.
"""

from allps.agent.contracts import (
    CandidateHandoverBrief,
    HandoverStatus,
    SynthesizedFinding,
)
from allps.agent.adapter import (
    DeterministicMockClient,
    InferenceClient,
    InferenceError,
    InferenceTimeoutError,
    InferenceUnavailableError,
    LocalOpenAIClient,
)
from allps.agent.validator import (
    OutputValidator,
    ValidationResult,
)
from allps.agent.orchestrator import (
    AgentOrchestrator,
    OrchestrationResult,
)

__all__ = [
    "CandidateHandoverBrief",
    "HandoverStatus",
    "SynthesizedFinding",
    "InferenceClient",
    "LocalOpenAIClient",
    "DeterministicMockClient",
    "InferenceError",
    "InferenceTimeoutError",
    "InferenceUnavailableError",
    "OutputValidator",
    "ValidationResult",
    "AgentOrchestrator",
    "OrchestrationResult",
]
