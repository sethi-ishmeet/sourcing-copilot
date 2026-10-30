"""Every endpoint except /api/health needs a key, and only a recruiter can act."""

from __future__ import annotations

from tests.api.conftest import RECRUITER, VIEWER, start_screening


def test_health_needs_no_key(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "fake"}


def test_missing_key_is_401(client):
    response = client.get("/api/roles")
    assert response.status_code == 401
    assert response.json()["detail"] == "missing X-API-Key header"


def test_unknown_key_is_401(client):
    response = client.get("/api/roles", headers={"X-API-Key": "nope"})
    assert response.status_code == 401
    assert response.json()["detail"] == "unknown API key"


def test_viewer_can_read(client):
    assert client.get("/api/roles", headers=VIEWER).status_code == 200
    assert client.get("/api/roles/role_backend_sr", headers=VIEWER).status_code == 200
    assert client.get("/api/candidates/cand_001", headers=VIEWER).status_code == 200
    assert client.get("/api/data-checks", headers=VIEWER).status_code == 200


def test_viewer_cannot_start_a_screening(client):
    response = client.post(
        "/api/roles/role_backend_sr/screenings", json={"candidate_id": "cand_001"}, headers=VIEWER
    )
    assert response.status_code == 403
    assert "only a recruiter" in response.json()["detail"]


def test_viewer_cannot_approve(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=VIEWER
    )
    assert response.status_code == 403
    # Nothing happened: still waiting.
    assert client.get(f"/api/screenings/{run_id}", headers=VIEWER).json()["status"] == (
        "awaiting_approval"
    )


def test_recruiter_can_do_everything(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "reject"}, headers=RECRUITER
    )
    assert response.status_code == 200
