"""
Unit and Integration Tests for US-034 Model / System Card Publication & Endpoints.
"""

import os
import pytest
from fastapi.testclient import TestClient

from backend.app.auth import create_access_token
from backend.app.main import app
from scripts.publish_model_card import publish_card

client = TestClient(app)


def get_admin_headers():
    token = create_access_token(identity="admin@example.com", roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


def get_user_headers():
    token = create_access_token(identity="user@example.com", roles=["user"])
    return {"Authorization": f"Bearer {token}"}


def test_publish_model_card_script_execution():
    version_sha = "abc123456789def"
    card_path = publish_card(version=version_sha)

    assert os.path.exists(card_path)
    with open(card_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert f"VigilRAG Pipeline v{version_sha}" in content
    assert "Governance Framework Mapping" in content
    assert "NIST AI RMF & ISO/IEC 42001" in content
    assert "Faithfulness" in content


def test_get_latest_model_card_admin_endpoint():
    # 1. Non-admin request -> 403 Forbidden
    non_admin_res = client.get("/api/v1/admin/model-cards/latest", headers=get_user_headers())
    assert non_admin_res.status_code == 403

    # 2. Admin request -> 200 OK
    admin_res = client.get("/api/v1/admin/model-cards/latest", headers=get_admin_headers())
    assert admin_res.status_code == 200
    assert "VigilRAG Pipeline" in admin_res.text
    assert "GOVERN 1.1" in admin_res.text


def test_get_version_model_card_admin_endpoint():
    version_sha = "v1.0.0-release"
    publish_card(version=version_sha)

    headers = get_admin_headers()
    res = client.get(f"/api/v1/admin/model-cards/{version_sha}", headers=headers)
    assert res.status_code == 200
    assert f"VigilRAG Pipeline v{version_sha}" in res.text
