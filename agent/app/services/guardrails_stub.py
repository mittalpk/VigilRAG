"""
Guardrails Service Module — re-exports GuardrailsClient from agent.app.guardrails.
"""

from agent.app.guardrails import GuardrailsClient, GuardrailsResult, FlaggedChunk, InjectionEvent

__all__ = ["GuardrailsClient", "GuardrailsResult", "FlaggedChunk", "InjectionEvent"]
