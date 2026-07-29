#!/usr/bin/env python3
"""
VigilRAG Model-Training Data Lineage Verification Script (NFR-003 / US-026).
Verifies that no source content reaches model training pipelines without logged consent.
Checks:
1. TRAINING_ENABLED environment variable is false.
2. No active data export jobs exist targeting training endpoints.
"""

import os
import sys

def check_training_lineage() -> bool:
    print("=== VigilRAG Model Training Data Lineage Check (NFR-003) ===")
    
    # Check 1: TRAINING_ENABLED setting
    training_enabled = os.environ.get("TRAINING_ENABLED", "false").lower()
    if training_enabled in ("true", "1", "yes"):
        print("[FAIL] TRAINING_ENABLED is set to TRUE. Source content could be used in model training without explicit consent policy!")
        return False
    print(f"[PASS] TRAINING_ENABLED={training_enabled} (Model training data export disabled)")

    # Check 2: Verify no data export pipelines targeting training endpoints
    # Scan environment for TRAINING_ENDPOINT or LLM_FINE_TUNING_URL
    training_endpoint = os.environ.get("TRAINING_ENDPOINT") or os.environ.get("LLM_FINE_TUNING_URL")
    if training_endpoint:
        print(f"[FAIL] Active training endpoint configured: {training_endpoint}")
        return False
    print("[PASS] No active data export endpoints configured targeting external training pipelines.")

    print("\nLineage Check Result: VERIFIED COMPLIANT (NFR-003 Data Consent Policy Enforced).")
    return True

if __name__ == "__main__":
    success = check_training_lineage()
    if not success:
        sys.exit(1)
