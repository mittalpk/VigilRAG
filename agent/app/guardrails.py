"""
VigilRAG Agent Service Guardrails Module for US-024.
Provides Prompt-Injection Defense scanning on retrieved content (evidence-in) and user query input.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATTERNS_PATH = os.path.join(os.path.dirname(__file__), "guardrails_patterns.yaml")


@dataclass
class FlaggedChunk:
    chunk_id: str
    pattern: str
    severity: str
    category: str
    action_taken: str


@dataclass
class InjectionEvent:
    trace_id: str
    chunk_id: str
    pattern: str
    severity: str
    category: str
    timestamp: str


@dataclass
class GuardrailsResult:
    safe_chunks: List[Dict[str, Any]] = field(default_factory=list)
    flagged_chunks: List[FlaggedChunk] = field(default_factory=list)
    injection_events: List[InjectionEvent] = field(default_factory=list)
    guardrail_flags: List[str] = field(default_factory=list)
    all_flagged: bool = False


class GuardrailsClient:
    """
    Guardrails client for prompt-injection detection, code-fence parsing,
    content sanitisation, and chunk exclusion.
    """

    def __init__(self, patterns_path: Optional[str] = None):
        self.patterns_path = patterns_path or DEFAULT_PATTERNS_PATH
        self.patterns: List[Dict[str, Any]] = []
        self.load_patterns()

    def load_patterns(self) -> None:
        """Loads prompt injection patterns from YAML configuration."""
        if not os.path.exists(self.patterns_path):
            logger.warning(f"Guardrails patterns file not found at {self.patterns_path}. Using fallback patterns.")
            self.patterns = [
                {"id": "INJ-FB-1", "phrase": "ignore previous instructions", "severity": "high", "category": "system_override"},
                {"id": "INJ-FB-2", "phrase": "disregard system prompt", "severity": "high", "category": "system_override"},
                {"id": "INJ-FB-3", "phrase": "you are now", "severity": "medium", "category": "role_play"},
            ]
            return

        try:
            with open(self.patterns_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                self.patterns = data.get("patterns", [])
        except Exception as exc:
            logger.error(f"Failed to load guardrails patterns from {self.patterns_path}: {exc}")
            raise RuntimeError(f"Guardrail patterns configuration unreadable: {exc}")

    @staticmethod
    def strip_code_fences(text: str) -> str:
        """
        Removes content enclosed in triple-backtick code fences (```...```)
        so code comments containing injection-like strings are not flagged.
        """
        if not text:
            return ""
        # Match triple backticks, optional language specifier, content, and closing backticks
        pattern = r"```[\s\S]*?```"
        return re.sub(pattern, "", text)

    def scan_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Scans text (outside code fences) for injection patterns.
        Returns list of matched pattern configs.
        """
        if not text:
            return []

        scannable_text = self.strip_code_fences(text).lower()
        matches = []
        for pattern_cfg in self.patterns:
            phrase = pattern_cfg.get("phrase", "").lower()
            if phrase and phrase in scannable_text:
                matches.append(pattern_cfg)
        return matches

    async def validate(self, input_text: str, trace_id: str = "") -> Tuple[str, List[str]]:
        """
        Validates user query input against prompt injection patterns.
        Returns (sanitized_input, guardrail_flags).
        """
        matches = self.scan_text(input_text)
        flags = []
        sanitized = input_text

        for match in matches:
            phrase = match["phrase"]
            severity = match.get("severity", "high")
            flag = f"query-injection-detected:{match['id']}"
            if flag not in flags:
                flags.append(flag)

            logger.warning(
                "query_injection_detected",
                extra={
                    "trace_id": trace_id,
                    "pattern": phrase,
                    "severity": severity,
                    "category": match.get("category", "unknown"),
                },
            )

            if severity in ("high", "medium"):
                pattern_re = re.compile(re.escape(phrase), re.IGNORECASE)
                sanitized = pattern_re.sub("[REDACTED_INJECTION_ATTEMPT]", sanitized)

        return sanitized, flags

    def scan_evidence(self, chunks: List[Dict[str, Any]], trace_id: str = "") -> GuardrailsResult:
        """
        Scans a list of evidence chunks for prompt-injection patterns before synthesis.
        Applies pattern severity rules:
        - high: Exclude chunk from synthesis.
        - medium: Sanitise chunk (strip injection phrase).
        - low: Log event, retain chunk.
        """
        result = GuardrailsResult()

        if not chunks:
            return result

        safe_chunks = []
        total_chunks = len(chunks)
        excluded_count = 0

        for chunk in chunks:
            chunk_id = str(chunk.get("chunk_id", chunk.get("id", "unknown")))
            content = str(chunk.get("content", ""))

            matches = self.scan_text(content)
            if not matches:
                safe_chunks.append(chunk)
                continue

            # Process matched injection patterns
            highest_severity = "low"
            modified_content = content
            chunk_flagged = False

            for match in matches:
                phrase = match.get("phrase", "")
                severity = match.get("severity", "high")
                category = match.get("category", "unknown")
                pattern_id = match.get("id", "unknown")

                timestamp = datetime.utcnow().isoformat() + "Z"
                event = InjectionEvent(
                    trace_id=trace_id,
                    chunk_id=chunk_id,
                    pattern=phrase,
                    severity=severity,
                    category=category,
                    timestamp=timestamp,
                )
                result.injection_events.append(event)

                logger.warning(
                    f"Prompt injection detected in chunk '{chunk_id}' [pattern='{phrase}', severity='{severity}']",
                    extra={
                        "trace_id": trace_id,
                        "chunk_id": chunk_id,
                        "pattern": phrase,
                        "severity": severity,
                    },
                )

                if severity == "high":
                    highest_severity = "high"
                elif severity == "medium" and highest_severity != "high":
                    highest_severity = "medium"

                # Sanitise medium severity phrase in content copy
                if severity in ("medium", "high"):
                    pattern_re = re.compile(re.escape(phrase), re.IGNORECASE)
                    modified_content = pattern_re.sub("", modified_content)

                chunk_flagged = True

            flag_str = f"injection-detected-in-chunk-{chunk_id}"
            if flag_str not in result.guardrail_flags:
                result.guardrail_flags.append(flag_str)

            action_taken = "excluded" if highest_severity == "high" else ("sanitised" if highest_severity == "medium" else "logged_only")
            result.flagged_chunks.append(
                FlaggedChunk(
                    chunk_id=chunk_id,
                    pattern="; ".join(m.get("phrase", "") for m in matches),
                    severity=highest_severity,
                    category="; ".join(set(m.get("category", "unknown") for m in matches)),
                    action_taken=action_taken,
                )
            )

            if highest_severity == "high":
                excluded_count += 1
            else:
                # Retain sanitized or low-severity chunk
                chunk_copy = dict(chunk)
                chunk_copy["content"] = modified_content.strip()
                safe_chunks.append(chunk_copy)

        result.safe_chunks = safe_chunks
        if total_chunks > 0 and len(safe_chunks) == 0:
            result.all_flagged = True
            result.guardrail_flags.append("all-evidence-flagged")

        return result
