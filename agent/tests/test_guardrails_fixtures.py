"""
VigilRAG Guardrails Data-Driven CI Fixture Test Suite (US-027 / FR-012 / NFR-010).
Loads fixtures from:
- agent/tests/fixtures/injection_patterns.yaml
- agent/tests/fixtures/unsafe_outputs.yaml
- agent/tests/fixtures/pii_fixtures.yaml

Adding new fixtures to the YAML files automatically creates test cases without code changes.
"""

import os
import pytest
import yaml

from agent.app.guardrails import GuardrailsClient

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_yaml_fixtures(filename: str):
    filepath = os.path.join(FIXTURES_DIR, filename)
    if not os.path.exists(filepath):
        pytest.fail(f"Fixture file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("fixtures", [])


INJECTION_FIXTURES = load_yaml_fixtures("injection_patterns.yaml")
UNSAFE_OUTPUT_FIXTURES = load_yaml_fixtures("unsafe_outputs.yaml")
PII_FIXTURES = load_yaml_fixtures("pii_fixtures.yaml")


@pytest.fixture(scope="module")
def guardrails_client():
    return GuardrailsClient()


# ── 1. Injection Defense Fixture Suite (US-024) ───────────────────────────────

@pytest.mark.parametrize("fixture", INJECTION_FIXTURES, ids=lambda f: f["id"])
def test_injection_fixtures(guardrails_client, fixture):
    """
    Tests evidence content scanning against known prompt injection patterns
    and false positive pass cases.
    """
    chunk = {
        "chunk_id": f"chk-{fixture['id']}",
        "content": fixture["content"],
    }
    res = guardrails_client.scan_evidence([chunk], trace_id=f"trc-{fixture['id']}")
    expected = fixture.get("expected", "flagged")

    if expected == "pass":
        assert len(res.safe_chunks) == 1, f"Fixture {fixture['id']} failed: expected pass but chunk was excluded"
        assert len(res.flagged_chunks) == 0, f"Fixture {fixture['id']} failed: expected no flagged chunks"
        assert not res.all_flagged
    else:  # "flagged" or "blocked"
        assert (len(res.flagged_chunks) >= 1 or res.all_flagged), f"Fixture {fixture['id']} failed: expected injection to be flagged/excluded"
        assert f"injection-detected-in-chunk-chk-{fixture['id']}" in res.guardrail_flags


# ── 2. Unsafe Output / Structural Safety Fixture Suite (US-025) ──────────────

@pytest.mark.parametrize("fixture", UNSAFE_OUTPUT_FIXTURES, ids=lambda f: f["id"])
def test_unsafe_output_fixtures(guardrails_client, fixture):
    """
    Tests answer-out validation against schema errors, harmful content,
    and injection instruction echoes.
    """
    payload = fixture["payload"]
    res = guardrails_client.validate_output(payload, trace_id=payload.get("trace_id", f"trc-{fixture['id']}"))
    expected = fixture.get("expected", "pass")

    if expected == "pass":
        assert res.valid, f"Fixture {fixture['id']} failed: expected pass but got validation error '{res.reason}' ({res.details})"
        assert res.reason is None
    elif expected == "schema-invalid":
        assert not res.valid, f"Fixture {fixture['id']} failed: expected schema-invalid but validation passed"
        assert res.reason == "schema-invalid"
    elif expected == "safety-check-failed":
        assert not res.valid, f"Fixture {fixture['id']} failed: expected safety-check-failed but validation passed"
        assert res.reason == "safety-check-failed"
    else:
        pytest.fail(f"Unknown expected status in fixture {fixture['id']}: {expected}")


# ── 3. Presidio PII Redaction Fixture Suite (US-026) ──────────────────────────

@pytest.mark.parametrize("fixture", PII_FIXTURES, ids=lambda f: f["id"])
def test_pii_fixtures(guardrails_client, fixture):
    """
    Tests PII detection, redaction placeholders, and guardrail flags.
    """
    input_text = fixture["input"]
    res = guardrails_client.pii_redact(input_text, trace_id=f"trc-{fixture['id']}")

    expected_redacted = fixture["expected_redacted"]
    expected_flags = set(fixture["expected_flags"])

    assert res.redacted_text == expected_redacted, f"Fixture {fixture['id']} failed: redacted text mismatch"
    assert set(res.guardrail_flags) == expected_flags, f"Fixture {fixture['id']} failed: flags mismatch (got {res.guardrail_flags}, expected {expected_flags})"
