"""
Unit and Integration Tests for US-031 Source Registration Self-Service Router (/api/v1/admin/sources).
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.auth import create_access_token
from backend.app.main import app
from backend.app.models import AsyncSessionLocal, Source

client = TestClient(app)


def get_admin_headers():
    token = create_access_token(identity="admin@example.com", roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


def get_user_headers():
    token = create_access_token(identity="user@example.com", roles=["user"])
    return {"Authorization": f"Bearer {token}"}


def test_list_source_types_admin():
    response = client.get("/api/v1/admin/sources/types", headers=get_admin_headers())
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    type_ids = [t["type_id"] for t in data]
    assert "github_repo" in type_ids
    assert "confluence_wiki" in type_ids
    assert "wiki_local" in type_ids


def test_list_sources_non_admin_403():
    response = client.get("/api/v1/admin/sources", headers=get_user_headers())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_source_lifecycle_create_get_trigger_deactivate():
    from backend.app.models import init_db
    await init_db()

    headers = get_admin_headers()
    unique_repo = "https://github.com/org/test-us031-lifecycle-repo"

    # 1. Register Source
    payload = {
        "name": "US-031 Test GitHub Repo",
        "source_type": "github_repo",
        "endpoint_url": unique_repo,
        "secret_reference": "kv-secret-github-test-pat",
        "owner_email": "repo-owner@example.com",
        "sensitivity_level": "internal-general",
        "sensitivity_signed_off": True,
        "refresh_cadence_minutes": 1440,
        "indexing_scope": "docs/*",
    }
    create_res = client.post("/api/v1/admin/sources", json=payload, headers=headers)
    assert create_res.status_code == 201
    source_data = create_res.json()
    source_id = source_data["id"]
    assert source_data["name"] == "US-031 Test GitHub Repo"
    assert source_data["status"] == "pending_first_index"
    assert source_data["is_active"] is True

    # 2. Duplicate Registration -> HTTP 409
    dup_res = client.post("/api/v1/admin/sources", json=payload, headers=headers)
    assert dup_res.status_code == 409
    assert "already registered" in dup_res.json()["detail"]

    # 3. Get Source Detail
    detail_res = client.get(f"/api/v1/admin/sources/{source_id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["id"] == source_id

    # 4. Trigger Indexing -> transitions status to indexing
    trig_res = client.post(f"/api/v1/admin/sources/{source_id}/trigger-index", headers=headers)
    assert trig_res.status_code == 200
    assert trig_res.json()["status"] in ("indexing", "indexed")

    # 5. Update Source Configuration
    patch_res = client.patch(
        f"/api/v1/admin/sources/{source_id}",
        json={"name": "US-031 Updated Repo Name", "refresh_cadence_minutes": 720},
        headers=headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "US-031 Updated Repo Name"
    assert patch_res.json()["refresh_cadence_minutes"] == 720

    # 6. Deactivate Source (Soft-delete)
    deact_res = client.delete(f"/api/v1/admin/sources/{source_id}", headers=headers)
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False
    assert deact_res.json()["status"] == "inactive"
