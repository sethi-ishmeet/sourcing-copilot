"""End-to-end runs of the copilot with the fake model: the happy path, every way a run
can stop early, every built-in failure, and resuming after a restart."""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from sourcing_copilot.config import Settings
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from sourcing_copilot.data.profile import quote_is_in_profile

ROLE = "role_backend_sr"


def step_names(state):
    return [s["name"] for s in state["steps"]]


def tool_calls(state):
    return [s["details"]["input"] for s in state["steps"] if s["name"].startswith("tool: ")]


# -- happy path -----------------------------------------------------------------------


def test_strong_match_pauses_with_a_scorecard_and_a_draft(make_copilot, sample_data):
    copilot = make_copilot()
    state = copilot.start("run_1", ROLE, "cand_001")

    assert state["status"] == "awaiting_approval"
    assert copilot.is_waiting("run_1")
    assert state["tool_calls_made"] == 2
    assert [s["name"] for s in state["steps"] if s["name"].startswith("tool")] == [
        "tool: get_profile",
        "tool: check_do_not_contact",
    ]
    priya = sample_data.candidate("cand_001")
    for score in state["scorecard"]["scores"]:
        assert quote_is_in_profile(score["proof"], priya)
    assert state["scorecard"]["recommend"] is True
    assert 20 <= len(state["draft_message"]) <= 300
    assert "Acme Health" in state["draft_message"]
    assert all(r["passed"] for r in state["rule_results"])
    assert state["send_receipt"] is None


def test_approve_sends_the_draft_once(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    state = copilot.decide("run_1", "approve", decided_by="recruiter")

    assert state["status"] == "sent"
    assert not copilot.is_waiting("run_1")
    assert state["final_message"] == state["draft_message"]
    assert state["send_receipt"]["candidate_id"] == "cand_001"
    assert linkedin.sent_count == 1
    assert step_names(state)[-3:] == ["wait for approval", "send", "finish"]
    assert state["decision"]["decided_by"] == "recruiter"


def test_edit_then_approve_sends_the_edited_text(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    edited = "Hi Priya, Sam here from Acme Health. Your healthcare backend work stood out. Chat?"
    state = copilot.decide("run_1", "approve", decided_by="recruiter", message=edited)

    assert state["status"] == "sent"
    assert state["final_message"] == edited
    assert linkedin.attempts[0]["candidate_id"] == "cand_001"
    wait_step = next(s for s in state["steps"] if s["name"] == "wait for approval")
    assert wait_step["details"]["edited"] is True


def test_reject_sends_nothing(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    state = copilot.decide("run_1", "reject", decided_by="recruiter")

    assert state["status"] == "rejected"
    assert state["final_message"] is None
    assert linkedin.sent_count == 0 and linkedin.attempts == []


def test_an_edited_message_that_breaks_a_rule_is_not_sent(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    bad = "Hi Priya, Acme Health here, see https://example.com/role for details."
    state = copilot.decide("run_1", "approve", decided_by="recruiter", message=bad)

    assert state["status"] == "needs_review"
    assert "no_links_or_emails" in state["error"]
    assert linkedin.sent_count == 0


# -- stopping early -------------------------------------------------------------------


def test_clear_mismatch_is_not_recommended_and_gets_no_draft(make_copilot):
    state = make_copilot().start("run_1", ROLE, "cand_002")
    assert state["status"] == "not_recommended"
    assert state["scorecard"]["recommend"] is False
    assert state["draft_message"] is None
    assert "ask model to write message" not in step_names(state)


def test_do_not_contact_stops_before_scoring(make_copilot):
    state = make_copilot().start("run_1", ROLE, "cand_003")
    assert state["status"] == "do_not_contact"
    assert state["contact_allowed"] is False
    assert "Asked us not to contact them again" in state["error"]
    assert state["scorecard"] is None
    assert state["draft_message"] is None


def test_must_have_scored_zero_means_not_recommended(make_copilot):
    # Hannah has Python but only Azure; "GCP or AWS" is a must-have.
    state = make_copilot().start("run_1", ROLE, "cand_007")
    assert state["status"] == "not_recommended"
    cloud = next(s for s in state["scorecard"]["scores"] if s["requirement_id"] == "cloud")
    assert cloud["score"] == 0


# -- built-in failures ----------------------------------------------------------------


def test_hidden_instructions_in_a_profile_do_not_change_the_outcome(make_copilot):
    state = make_copilot().start("run_1", ROLE, "cand_004")
    assert state["status"] == "awaiting_approval"
    assert any("untrusted" in w for w in state["data_warnings"])
    assert "http" not in state["draft_message"]
    assert not all(s["score"] == 5 for s in state["scorecard"]["scores"])


def test_even_if_the_model_obeys_hidden_instructions_the_rules_stop_the_message(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(behaviour="follows_hidden_instructions", linkedin=linkedin)
    state = copilot.start("run_1", ROLE, "cand_004")
    assert state["status"] == "needs_review"
    assert "no_links_or_emails" in state["error"]
    assert "https://" in (state["draft_message"] or "")  # kept so a human can see what happened
    assert not copilot.is_waiting("run_1")
    assert linkedin.sent_count == 0


def test_out_of_date_profile_lowers_confidence_and_warns(make_copilot):
    state = make_copilot().start("run_1", ROLE, "cand_005")
    assert state["status"] == "awaiting_approval"
    assert state["scorecard"]["confidence"] == "low"
    assert any("881 days" in w for w in state["data_warnings"])
    assert any("days ago" in w for w in state["scorecard"]["warnings"])


def test_send_that_fails_once_is_retried_and_delivered_exactly_once(make_copilot):
    linkedin = PretendLinkedIn(fail_times=1)
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    state = copilot.decide("run_1", "approve", decided_by="recruiter")

    assert state["status"] == "sent"
    assert linkedin.sent_count == 1
    assert len(linkedin.attempts) == 2
    send_steps = [s for s in state["steps"] if s["name"] == "send"]
    assert [s["status"] for s in send_steps] == ["error", "ok"]


def test_send_fails_cleanly_when_linkedin_is_down(make_copilot):
    linkedin = PretendLinkedIn(down=True)
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    state = copilot.decide("run_1", "approve", decided_by="recruiter")

    assert state["status"] == "failed"
    assert "could not send after 3 attempts" in state["error"]
    assert linkedin.sent_count == 0


def test_runaway_model_is_stopped_by_the_tool_call_cap(make_copilot):
    copilot = make_copilot(behaviour="never_submits", settings=Settings(max_tool_calls=4))
    state = copilot.start("run_1", ROLE, "cand_001")
    assert state["status"] == "failed"
    assert state["error"] == "stopped after 4 tool calls without a scorecard"
    assert len(tool_calls(state)) == 4


def test_made_up_proof_is_sent_back_once_then_stops_for_review(make_copilot):
    state = make_copilot(behaviour="bad_proof").start("run_1", ROLE, "cand_001")
    assert state["status"] == "needs_review"
    assert "proof not found on the profile" in state["error"]
    assert step_names(state).count("scorecard rejected") == 2
    assert state["draft_message"] is None


def test_too_long_message_is_sent_back_then_stops_for_review(make_copilot):
    state = make_copilot(behaviour="too_long_message").start("run_1", ROLE, "cand_001")
    assert state["status"] == "needs_review"
    assert "message_length" in state["error"]
    assert step_names(state).count("draft rejected") == 2


def test_model_outage_fails_the_run_with_a_clear_error(make_copilot):
    state = make_copilot(behaviour="crash").start("run_1", ROLE, "cand_001")
    assert state["status"] == "failed"
    assert state["error"] == "model call failed twice: fake model crashed on purpose"
    assert state["steps"][-2]["status"] == "error"


def test_model_cannot_read_another_candidates_profile(make_copilot):
    copilot = make_copilot(behaviour="looks_up_someone_else")
    state = copilot.start("run_1", ROLE, "cand_001")
    first_lookup = next(s for s in state["steps"] if s["name"] == "tool: get_profile")
    assert first_lookup["status"] == "error"
    assert "not allowed" in first_lookup["details"]["output"]["error"]
    assert state["profile"]["id"] == "cand_001"
    assert state["status"] == "awaiting_approval"


# -- durability -----------------------------------------------------------------------


def test_a_paused_run_survives_a_restart(make_copilot, tmp_path):
    db = tmp_path / "checkpoints.sqlite"
    first = make_copilot(checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)))
    first.start("run_1", ROLE, "cand_001")
    assert first.is_waiting("run_1")

    # "Restart": a brand new copilot and checkpointer over the same file.
    linkedin = PretendLinkedIn()
    second = make_copilot(
        linkedin=linkedin,
        checkpointer=SqliteSaver(sqlite3.connect(db, check_same_thread=False)),
    )
    assert second.is_waiting("run_1")
    state = second.decide("run_1", "approve", decided_by="recruiter")
    assert state["status"] == "sent"
    assert linkedin.sent_count == 1


# -- started from LangGraph Studio, where the input is whatever the user typed ---------


def test_missing_ids_fail_readably_and_a_run_id_is_filled_in(make_copilot):
    copilot = make_copilot()
    copilot.graph.invoke({"status": "screening"}, {"configurable": {"thread_id": "t1"}})
    state = copilot.graph.get_state({"configurable": {"thread_id": "t1"}}).values
    assert state["status"] == "failed"
    assert "both ids are required" in state["error"]
    assert state["run_id"].startswith("run_")


def test_a_bare_approve_string_works_as_a_decision(make_copilot):
    linkedin = PretendLinkedIn()
    copilot = make_copilot(linkedin=linkedin)
    copilot.start("run_1", ROLE, "cand_001")
    copilot.graph.invoke(Command(resume="approve"), {"configurable": {"thread_id": "run_1"}})
    state = copilot.state("run_1")
    assert state["status"] == "sent"
    assert state["decision"]["decided_by"] == "studio"
    assert linkedin.sent_count == 1


def test_an_unknown_decision_stops_for_review_instead_of_crashing(make_copilot):
    copilot = make_copilot()
    copilot.start("run_1", ROLE, "cand_001")
    copilot.graph.invoke(Command(resume="maybe"), {"configurable": {"thread_id": "run_1"}})
    state = copilot.state("run_1")
    assert state["status"] == "needs_review"
    assert "must be approve or reject" in state["error"]
