"""Reads: roles, candidates, data checks. Also the data-presentation tests: numbers the
UI shows come out of the API the way the data layer computed them."""

from __future__ import annotations

from tests.api.conftest import VIEWER, start_screening


def test_list_roles(client):
    roles = client.get("/api/roles", headers=VIEWER).json()
    assert [r["id"] for r in roles] == ["role_backend_sr", "role_ml_platform"]
    assert roles[0]["shortlist_size"] == 8


def test_unknown_role_and_candidate_are_404(client):
    assert client.get("/api/roles/role_nope", headers=VIEWER).status_code == 404
    assert client.get("/api/candidates/cand_nope", headers=VIEWER).status_code == 404
    assert client.get("/api/screenings/run_nope", headers=VIEWER).status_code == 404
    assert client.get("/api/screenings/run_nope/steps", headers=VIEWER).status_code == 404


def test_role_page_presents_computed_candidate_facts(client):
    role = client.get("/api/roles/role_backend_sr", headers=VIEWER).json()
    assert [r["id"] for r in role["requirements"]] == [
        "python_backend",
        "cloud",
        "postgres",
        "regulated",
    ]
    by_id = {c["id"]: c for c in role["candidates"]}
    assert list(by_id) == role_shortlist_order()

    priya = by_id["cand_001"]
    assert priya["years_of_experience"] == 7.7
    assert priya["current_title"] == "Senior Backend Engineer"
    assert priya["current_company"] == "Northwind Health"
    assert priya["is_stale"] is False
    assert priya["latest_screening"] is None

    aisha = by_id["cand_005"]
    assert aisha["is_stale"] is True
    assert aisha["data_warnings"] == ["profile last updated 881 days ago"]

    daniel = by_id["cand_004"]
    assert any("untrusted" in w for w in daniel["data_warnings"])


def role_shortlist_order():
    return [
        "cand_001",
        "cand_002",
        "cand_003",
        "cand_004",
        "cand_005",
        "cand_007",
        "cand_008",
        "cand_009",
    ]


def test_candidate_page_presents_the_profile(client):
    priya = client.get("/api/candidates/cand_001", headers=VIEWER).json()
    assert priya["full_name"] == "Priya Raman"
    assert priya["days_since_update"] == 46
    assert priya["skills"][:2] == ["Python", "FastAPI"]
    assert priya["experience"][0]["company"] == "Northwind Health"
    assert priya["about_written_by_candidate"].startswith("Backend engineer")


def test_data_checks_endpoint_reports_the_planted_warnings(client):
    checks = client.get("/api/data-checks", headers=VIEWER).json()
    assert checks["errors"] == 0
    assert checks["warnings"] == 3
    assert {p["check"] for p in checks["problems"]} == {
        "stale_profile",
        "suspicious_text",
        "do_not_contact_unmatched",
    }


def test_role_page_shows_the_latest_screening_per_candidate(client):
    first = start_screening(client, "cand_001").json()["run_id"]
    second = start_screening(client, "cand_001").json()["run_id"]
    role = client.get("/api/roles/role_backend_sr", headers=VIEWER).json()
    priya = next(c for c in role["candidates"] if c["id"] == "cand_001")
    assert priya["latest_screening"]["run_id"] == second
    assert priya["latest_screening"]["run_id"] != first
    assert priya["latest_screening"]["status"] == "awaiting_approval"
