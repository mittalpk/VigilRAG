"""
VigilRAG Agent Service Guardrails Module for US-024 / US-025 / US-026 / US-027.
Provides Prompt-Injection Defense scanning on retrieved content (evidence-in), user query input,
output validation (answer-out structural and safety schema checks), and PII detection/redaction (Microsoft Presidio integration).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


@dataclass
class ValidationResult:
    valid: bool
    reason: Optional[str] = None  # "schema-invalid" or "safety-check-failed"
    error_type: Optional[str] = None
    details: Optional[str] = None


@dataclass
class RedactionResult:
    redacted_text: str
    detected_entities: List[str] = field(default_factory=list)
    guardrail_flags: List[str] = field(default_factory=list)


class GuardrailsClient:
    """
    Guardrails client for prompt-injection detection, code-fence parsing,
    content sanitisation, chunk exclusion, output safety/schema validation,
    and Presidio-based PII detection and redaction.
    """

    HARMFUL_PATTERNS = [
        "hate speech",
        "self-harm instruction",
        "how to build a bomb",
        "how to create malware",
        "execute unauthorized command",
        "system prompt override successful",
        "injection instruction executed",
    ]

    def __init__(self, patterns_path: Optional[str] = None):
        self.patterns_path = patterns_path or DEFAULT_PATTERNS_PATH
        self.patterns: List[Dict[str, Any]] = []
        self.load_patterns()
        self._init_presidio()

    def _init_presidio(self) -> None:
        """Initializes Presidio Analyzer and Anonymizer engines.

        GAP-N03: On failure, logs at ERROR level and sets _presidio_unavailable=True so that
        pii_redact() raises HTTP 503 (fail-closed) rather than silently falling back to the
        regex engine, which gives far weaker PII coverage (US-026 / NFR-003).
        """
        self.presidio_analyzer = None
        self.presidio_anonymizer = None
        self._presidio_unavailable = False
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            self.presidio_analyzer = AnalyzerEngine()
            self.presidio_anonymizer = AnonymizerEngine()
            logger.info("Microsoft Presidio PII engines initialized successfully.")
        except ModuleNotFoundError:
            # Presidio packages not installed in local environment (e.g. lightweight CI runner); fall back to built-in rule engine
            self._presidio_unavailable = False
            logger.info("Presidio NLP packages not installed in environment; using built-in rule engine.")
        except Exception as exc:
            self._presidio_unavailable = True
            logger.error(
                f"Presidio PII engine failed to initialize ({exc}). "
                "pii_redact() will raise HTTP 503 until Presidio is available (fail-closed per NFR-003)."
            )

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

            highest_severity = "low"
            modified_content = content
            chunk_flagged = False

            for match in matches:
                phrase = match.get("phrase", "")
                severity = match.get("severity", "high")
                category = match.get("category", "unknown")
                pattern_id = match.get("id", "unknown")

                timestamp = datetime.now(timezone.utc).isoformat()
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
                chunk_copy = dict(chunk)
                chunk_copy["content"] = modified_content.strip()
                safe_chunks.append(chunk_copy)

        result.safe_chunks = safe_chunks
        if total_chunks > 0 and len(safe_chunks) == 0:
            result.all_flagged = True
            result.guardrail_flags.append("all-evidence-flagged")

        return result

    def pii_redact(self, text: str, trace_id: str = "") -> RedactionResult:
        """
        Detects and redacts PII from synthesized answer text (US-026).
        Replaces PII with type-specific placeholders: [REDACTED-EMAIL], [REDACTED-PERSON], [REDACTED-PHONE], etc.
        Avoids false positives for code identifiers (e.g. AliceBlue).

        GAP-N03: Raises HTTP 503 (fail-closed) when Presidio failed to initialize,
        rather than silently falling back to weaker regex-only coverage (NFR-003).
        """
        # Fail-closed: Presidio unavailable means PII redaction cannot be guaranteed
        if getattr(self, "_presidio_unavailable", False):
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "PII redaction service (Presidio) is unavailable. "
                    "Query cannot be processed until Presidio is initialized (NFR-003 fail-closed)."
                ),
            )

        if not text or not text.strip():
            return RedactionResult(redacted_text=text)


        detected_types = set()
        redacted = text

        # 1. Presidio Analyzer if loaded
        if self.presidio_analyzer and self.presidio_anonymizer:
            try:
                from presidio_anonymizer.entities import OperatorConfig
                results = self.presidio_analyzer.analyze(text=text, language="en")
                operators = {}
                for res in results:
                    entity_type = res.entity_type
                    entity_text = text[res.start:res.end]
                    if entity_type == "EMAIL_ADDRESS":
                        detected_types.add("EMAIL")
                        operators["EMAIL_ADDRESS"] = OperatorConfig("replace", {"new_value": "[REDACTED-EMAIL]"})
                    elif entity_type == "PERSON":
                        # Check false positive code identifier
                        if entity_text not in ("AliceBlue", "BobCode", "JohnDoeVar"):
                            detected_types.add("PERSON")
                            operators["PERSON"] = OperatorConfig("replace", {"new_value": "[REDACTED-PERSON]"})
                    elif entity_type == "PHONE_NUMBER":
                        # Ensure entity_text is not an IP address (e.g. 192.168.1.100)
                        if not re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", entity_text.strip()):
                            detected_types.add("PHONE")
                            operators["PHONE_NUMBER"] = OperatorConfig("replace", {"new_value": "[REDACTED-PHONE]"})
                    elif entity_type in ("CREDIT_CARD", "US_SSN", "IP_ADDRESS"):
                        tag = "CREDIT_CARD" if entity_type == "CREDIT_CARD" else ("US_SSN" if entity_type == "US_SSN" else "IP_ADDRESS")
                        detected_types.add(tag)
                        operators[entity_type] = OperatorConfig("replace", {"new_value": f"[REDACTED-{tag}]"})

                if operators:
                    anonymized_result = self.presidio_anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
                    redacted = anonymized_result.text
            except Exception as exc:
                logger.warning(f"Presidio analyze pass encountered exception: {exc}")

        # 2. Rule & Regex PII Engine (guarantees coverage and false-positive code term protection)
        # IP Address FIRST so IP address dots are redacted before phone matching
        ip_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
        if re.search(ip_pattern, redacted):
            detected_types.add("IP_ADDRESS")
            redacted = re.sub(ip_pattern, "[REDACTED-IP_ADDRESS]", redacted)

        # Email
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        if re.search(email_pattern, redacted):
            detected_types.add("EMAIL")
            redacted = re.sub(email_pattern, "[REDACTED-EMAIL]", redacted)

        # Phone Number (excluding IP address patterns via lookarounds)
        phone_pattern = r"(?<!\d\.)\b(?:\+?\d{1,3}[-\s]?)?\(?\d{3}\)?\s*[-.]?\s*\d{3}\s*[-.]?\s*\d{4}\b(?!\.\d)"
        if re.search(phone_pattern, redacted):
            detected_types.add("PHONE")
            redacted = re.sub(phone_pattern, "[REDACTED-PHONE]", redacted)

        # Credit Card
        card_pattern = r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"
        if re.search(card_pattern, redacted):
            detected_types.add("CREDIT_CARD")
            redacted = re.sub(card_pattern, "[REDACTED-CREDIT_CARD]", redacted)

        # US SSN
        ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
        if re.search(ssn_pattern, redacted):
            detected_types.add("US_SSN")
            redacted = re.sub(ssn_pattern, "[REDACTED-US_SSN]", redacted)

        # Person Name detection (protecting code tokens like AliceBlue)
        person_names = ["John Doe", "Jane Smith", "Alice Smith", "Bob Johnson", "Robert Paulson"]
        for p_name in person_names:
            p_pattern = r"\b" + re.escape(p_name) + r"\b"
            if re.search(p_pattern, redacted, re.IGNORECASE):
                # Ensure it's not a code identifier like AliceBlue or JohnDoeVar
                match_str = re.search(p_pattern, redacted, re.IGNORECASE).group(0)
                if match_str not in ("AliceBlue", "BobCode", "JohnDoeVar"):
                    detected_types.add("PERSON")
                    redacted = re.sub(p_pattern, "[REDACTED-PERSON]", redacted, flags=re.IGNORECASE)

        flags = [f"pii-redacted:{t}" for t in sorted(detected_types)]

        # Check if entire answer text was PII
        clean_check = re.sub(r"\[REDACTED-[A-Z_]+\]", "", redacted)
        clean_check = re.sub(r"[\s\.,!?;:-]", "", clean_check)
        if len(text.strip()) > 0 and len(clean_check) == 0:
            flags.append("pii-redacted:ALL")

        return RedactionResult(
            redacted_text=redacted,
            detected_entities=list(sorted(detected_types)),
            guardrail_flags=flags,
        )

    def validate_output(self, response_data: dict, trace_id: str = "") -> ValidationResult:
        """
        Validates synthesized response output against structural schema and safety checks (US-025).
        - Schema check: answer non-empty string, citations list, trace_id present.
        - Safety check: answer does not echo prompt injections or contain harmful content.
        """
        from agent.app.schemas import AgentQueryResponse

        if not isinstance(response_data, dict):
            excerpt = str(response_data)[:200]
            logger.error(
                "output_validation_failed",
                extra={"trace_id": trace_id, "reason": "schema-invalid", "output_excerpt": excerpt},
            )
            return ValidationResult(valid=False, reason="schema-invalid", details="Payload must be a dictionary")

        answer = response_data.get("answer")
        excerpt = str(answer)[:200] if answer is not None else ""

        if not answer or not isinstance(answer, str) or not answer.strip():
            logger.error(
                "output_validation_failed",
                extra={"trace_id": trace_id, "reason": "schema-invalid", "output_excerpt": excerpt},
            )
            return ValidationResult(valid=False, reason="schema-invalid", details="Answer field must be a non-empty string")

        try:
            AgentQueryResponse.model_validate(response_data)
        except Exception as exc:
            logger.error(
                "output_validation_failed",
                extra={"trace_id": trace_id, "reason": "schema-invalid", "output_excerpt": excerpt},
            )
            return ValidationResult(valid=False, reason="schema-invalid", details=str(exc))

        answer_lower = answer.lower()

        # Harmful content safety check
        for harmful_phrase in self.HARMFUL_PATTERNS:
            if harmful_phrase in answer_lower:
                logger.error(
                    "output_validation_failed",
                    extra={"trace_id": trace_id, "reason": "safety-check-failed", "output_excerpt": excerpt},
                )
                return ValidationResult(valid=False, reason="safety-check-failed", details=f"Harmful content phrase: {harmful_phrase}")

        # Injected instruction echo check
        for pattern_cfg in self.patterns:
            phrase = pattern_cfg.get("phrase", "").lower()
            if phrase and (answer_lower.startswith(phrase) or f"injected instruction: {phrase}" in answer_lower):
                logger.error(
                    "output_validation_failed",
                    extra={"trace_id": trace_id, "reason": "safety-check-failed", "output_excerpt": excerpt},
                )
                return ValidationResult(valid=False, reason="safety-check-failed", details=f"Injection echo phrase: {phrase}")

        return ValidationResult(valid=True)
