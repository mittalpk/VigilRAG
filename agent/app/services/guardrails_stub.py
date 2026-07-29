"""
Guardrails Service Module — re-exports GuardrailsClient and result structures from agent.app.guardrails.
"""

from agent.app.guardrails import GuardrailsClient, GuardrailsResult, FlaggedChunk, InjectionEvent, ValidationResult

__all__ = ["GuardrailsClient", "GuardrailsResult", "FlaggedChunk", "InjectionEvent", "ValidationResult"]
