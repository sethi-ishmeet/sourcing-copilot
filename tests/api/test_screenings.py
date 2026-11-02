"""Starting a screening, reading it back, and deciding on it: success, validation,
and failure scenarios."""

from __future__ import annotations

from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from tests.api.conftest import RECRUITER, VIEWER, start_screening

# -- success ------------------------------------------------------------------------


def test_start_screening_returns_the_scorecard_and_draft(client):
    response = start_screening(client, "cand_001")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "awaiting_approval"
    assert body["candidate_name"] == "Priya Raman"
    assert body["role_title"] == "Senior Backend Engineer"
    assert body["started_by"] == "recruiter"
    assert len(body["scorecard"]["scores"]) == 4
    assert body["scorecard"]["recommend"] is True
    assert 20 <= len(body["draft_message"]) <= 300
    assert body["tokens_in"] > 0
    assert [s["name"] for s in body["steps"]][:2] == ["ask model to screen", "tool: get_profile"]
    assert "details" not in body["steps"][0]  # details live on the /steps endpoint


def test_get_screening_matches_what_start_returned(client):
    started = start_screening(client, "cand_001").json()
    fetched = client.get(f"/api/screenings/{started['run_id']}", headers=VIEWER).json()
    assert fetched == started


def test_steps_endpoint_has_the_full_trace_and_audit_log(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    trace = client.get(f"/api/screenings/{run_id}/steps", headers=VIEWER).json()
    names = [s["name"] for s in trace["steps"]]
    assert names == [
        "ask model to screen",
        "tool: get_profile",
        "ask model to screen",
        "tool: check_do_not_contact",
        "ask model to screen",
        "scorecard accepted",
        "check scorecard",
        "ask model to write message",
        "draft accepted",
        "check message",
    ]
    profile_step = trace["steps"][1]
    assert profile_step["details"]["input"] == {"candidate_id": "cand_001"}
    assert profile_step["details"]["output"]["full_name"] == "Priya Raman"
    assert all("ms" in s and "started_at" in s for s in trace["steps"])
    assert [(a["actor"], a["action"]) for a in trace["audit"]] == [
        ("recruiter", "started"),
        ("copilot", "awaiting_approval"),
    ]


def test_approve_sends_and_records_who_approved(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=RECRUITER
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body["decision"]["decided_by"] == "recruiter"
    assert body["send_receipt"]["candidate_id"] == "cand_001"
    assert body["final_message"] == body["draft_message"]
    audit = client.get(f"/api/screenings/{run_id}/steps", headers=VIEWER).json()["audit"]
    assert [(a["actor"], a["action"]) for a in audit][-2:] == [
        ("recruiter", "approved"),
        ("copilot", "sent"),
    ]


def test_edit_then_approve_sends_the_edited_text(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    edited = "Hi Priya, Sam from Acme Health here. Your clinic work stood out. Up for a chat?"
    body = client.post(
        f"/api/screenings/{run_id}/decision",
        json={"action": "approve", "message": edited},
        headers=RECRUITER,
    ).json()
    assert body["status"] == "sent"
    assert body["final_message"] == edited
    audit = client.get(f"/api/screenings/{run_id}/steps", headers=VIEWER).json()["audit"]
    assert ("recruiter", "approved", "edited the draft") in [
        (a["actor"], a["action"], a["detail"]) for a in audit
    ]


def test_reject_sends_nothing(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    body = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "reject"}, headers=RECRUITER
    ).json()
    assert body["status"] == "rejected"
    assert body["send_receipt"] is None


def test_not_recommended_and_do_not_contact_come_back_as_finished_screenings(client):
    marcus = start_screening(client, "cand_002").json()
    assert marcus["status"] == "not_recommended" and marcus["draft_message"] is None
    elena = start_screening(client, "cand_003").json()
    assert elena["status"] == "do_not_contact"
    assert "Asked us not to contact them again" in elena["error"]


# -- validation -----------------------------------------------------------------------


def test_missing_candidate_id_is_422(client):
    response = client.post("/api/roles/role_backend_sr/screenings", json={}, headers=RECRUITER)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "candidate_id"]


def test_bad_action_is_422(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "maybe"}, headers=RECRUITER
    )
    assert response.status_code == 422


def test_unknown_role_or_candidate_is_404(client):
    assert start_screening(client, "cand_001", role_id="role_nope").status_code == 404
    assert start_screening(client, "cand_nope").status_code == 404
    response = client.post(
        "/api/screenings/run_nope/decision", json={"action": "approve"}, headers=RECRUITER
    )
    assert response.status_code == 404


def test_candidate_not_on_the_shortlist_is_400(client):
    response = start_screening(client, "cand_006")  # Tomas is on the ML role, not this one
    assert response.status_code == 400
    assert response.json()["detail"] == "Tomas Herrera is not on this role's shortlist"


def test_edited_message_that_breaks_a_rule_is_422_and_the_run_keeps_waiting(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision",
        json={"action": "approve", "message": "Hi Priya, see https://example.com, Acme Health"},
        headers=RECRUITER,
    )
    assert response.status_code == 422
    assert [r["rule"] for r in response.json()["detail"]["rules"]] == ["no_links_or_emails"]
    assert client.get(f"/api/screenings/{run_id}", headers=VIEWER).json()["status"] == (
        "awaiting_approval"
    )


def test_approving_an_emptied_message_is_422_and_the_run_keeps_waiting(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    response = client.post(
        f"/api/screenings/{run_id}/decision",
        json={"action": "approve", "message": "   "},
        headers=RECRUITER,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "the edited message is empty"
    assert client.get(f"/api/screenings/{run_id}", headers=VIEWER).json()["status"] == (
        "awaiting_approval"
    )


def test_deciding_twice_is_409(client):
    run_id = start_screening(client, "cand_001").json()["run_id"]
    client.post(f"/api/screenings/{run_id}/decision", json={"action": "reject"}, headers=RECRUITER)
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=RECRUITER
    )
    assert response.status_code == 409
    assert "not waiting for approval" in response.json()["detail"]


def test_deciding_on_a_finished_screening_is_409(client):
    run_id = start_screening(client, "cand_002").json()["run_id"]  # not recommended
    response = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=RECRUITER
    )
    assert response.status_code == 409


# -- failures -------------------------------------------------------------------------


def test_model_outage_shows_up_as_a_failed_screening_not_a_500(make_client):
    client = make_client(behaviour="crash")
    response = start_screening(client, "cand_001")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "model call failed twice" in body["error"]


def test_bad_tool_arguments_from_the_model_are_not_a_500(make_client):
    response = start_screening(make_client(behaviour="bad_tool_arguments"), "cand_001")
    assert response.status_code == 201
    assert response.json()["status"] == "awaiting_approval"


def test_an_unexpected_crash_marks_the_screening_failed_instead_of_stuck(client, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(client.app.state.copilot, "start", crash)
    response = start_screening(client, "cand_001")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "unexpected error: something nobody planned for"
    saved = client.get(f"/api/screenings/{body['run_id']}", headers=VIEWER).json()
    assert saved["status"] == "failed"


def test_send_that_fails_once_still_ends_as_sent_once(make_client):
    linkedin = PretendLinkedIn(fail_times=1)
    client = make_client(linkedin=linkedin)
    run_id = start_screening(client, "cand_001").json()["run_id"]
    body = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=RECRUITER
    ).json()
    assert body["status"] == "sent"
    assert linkedin.sent_count == 1
    steps = client.get(f"/api/screenings/{run_id}/steps", headers=VIEWER).json()["steps"]
    assert [s["status"] for s in steps if s["name"] == "send"] == ["error", "ok"]


def test_linkedin_down_ends_as_failed_with_the_reason(make_client):
    linkedin = PretendLinkedIn(down=True)
    client = make_client(linkedin=linkedin)
    run_id = start_screening(client, "cand_001").json()["run_id"]
    body = client.post(
        f"/api/screenings/{run_id}/decision", json={"action": "approve"}, headers=RECRUITER
    ).json()
    assert body["status"] == "failed"
    assert "LinkedIn is not responding" in body["error"]
    audit = client.get(f"/api/screenings/{run_id}/steps", headers=VIEWER).json()["audit"]
    assert audit[-1]["action"] == "failed"


def test_hidden_instructions_followed_by_the_model_are_stopped_before_anyone_sees_a_send(
    make_client,
):
    client = make_client(behaviour="follows_hidden_instructions")
    body = start_screening(client, "cand_004").json()
    assert body["status"] == "needs_review"
    assert "no_links_or_emails" in body["error"]
    assert any(not r["passed"] for r in body["rule_results"])
