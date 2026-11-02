"""Each rule catches what it is named for. Rules run on the model's output and on text a
recruiter edits, so they are tested on their own, without the model."""

from __future__ import annotations

from sourcing_copilot.copilot import rules
from sourcing_copilot.copilot.schemas import RequirementScore, Scorecard


def _scorecard(scores, recommend=True):
    return Scorecard(
        scores=scores, recommend=recommend, confidence="high", summary="x", warnings=[]
    )


def _priya_scores(sample_data):
    return [
        RequirementScore(requirement_id="python_backend", score=5, reason="r", proof="FastAPI"),
        RequirementScore(requirement_id="cloud", score=5, reason="r", proof="Google Cloud"),
        RequirementScore(requirement_id="postgres", score=4, reason="r", proof="PostgreSQL"),
        RequirementScore(requirement_id="regulated", score=3, reason="r", proof="healthcare"),
    ]


def rule(results, name):
    return next(r for r in results if r.rule == name)


def test_good_scorecard_passes_every_rule(sample_data):
    role = sample_data.role("role_backend_sr")
    priya = sample_data.candidate("cand_001")
    results = rules.check_scorecard(_scorecard(_priya_scores(sample_data)), role, priya)
    assert rules.failed(results) == []


def test_missing_or_extra_requirement_fails_coverage(sample_data):
    role = sample_data.role("role_backend_sr")
    priya = sample_data.candidate("cand_001")
    scores = _priya_scores(sample_data)[:3]
    results = rules.check_scorecard(_scorecard(scores), role, priya)
    assert not rule(results, "covers_every_requirement").passed


def test_made_up_proof_fails(sample_data):
    role = sample_data.role("role_backend_sr")
    priya = sample_data.candidate("cand_001")
    scores = _priya_scores(sample_data)
    scores[0].proof = "Ten years running the Google Cloud platform team"
    results = rules.check_scorecard(_scorecard(scores), role, priya)
    r = rule(results, "proof_is_on_the_profile")
    assert not r.passed and "python_backend" in r.detail


def test_the_candidates_name_is_not_proof(sample_data):
    # A frontend developer scored 5/5 on every backend requirement, "proved" by his name.
    role = sample_data.role("role_backend_sr")
    marcus = sample_data.candidate("cand_002")
    scores = [
        RequirementScore(requirement_id=r.id, score=5, reason="r", proof="Marcus Oyelaran")
        for r in role.requirements
    ]
    r = rule(rules.check_scorecard(_scorecard(scores), role, marcus), "proof_is_on_the_profile")
    assert not r.passed and "python_backend" in r.detail


def test_empty_proof_is_fine_only_for_a_zero_score(sample_data):
    role = sample_data.role("role_backend_sr")
    priya = sample_data.candidate("cand_001")
    scores = _priya_scores(sample_data)
    scores[3] = RequirementScore(requirement_id="regulated", score=0, reason="none", proof="")
    assert rule(
        rules.check_scorecard(_scorecard(scores), role, priya), "proof_is_on_the_profile"
    ).passed
    scores[3] = RequirementScore(requirement_id="regulated", score=2, reason="some", proof="")
    assert not rule(
        rules.check_scorecard(_scorecard(scores), role, priya), "proof_is_on_the_profile"
    ).passed


def test_recommending_with_a_weak_must_have_fails(sample_data):
    role = sample_data.role("role_backend_sr")
    priya = sample_data.candidate("cand_001")
    scores = _priya_scores(sample_data)
    scores[1] = RequirementScore(requirement_id="cloud", score=1, reason="thin", proof="GCP")
    results = rules.check_scorecard(_scorecard(scores, recommend=True), role, priya)
    r = rule(results, "recommendation_matches_scores")
    assert not r.passed and "cloud" in r.detail
    # Not recommending is always consistent.
    results = rules.check_scorecard(_scorecard(scores, recommend=False), role, priya)
    assert rule(results, "recommendation_matches_scores").passed


def test_message_rules_pass_for_a_normal_message(sample_data):
    role = sample_data.role("role_backend_sr")
    text = "Hi Priya, I'm Sam at Acme Health. Open to a quick chat about a backend role?"
    assert rules.failed(rules.check_message(text, role)) == []


def test_message_too_long_or_too_short_fails(sample_data):
    role = sample_data.role("role_backend_sr")
    assert not rule(rules.check_message("Hi Acme Health", role), "message_length").passed
    long_text = "Acme Health " + "x" * 300
    assert not rule(rules.check_message(long_text, role), "message_length").passed


def test_links_and_emails_are_blocked(sample_data):
    role = sample_data.role("role_backend_sr")
    for bad in [
        "Hi, Acme Health here, see https://example.com/me",
        "Hi, Acme Health here, see www.example.com",
        "Hi, Acme Health here, write to sam@acme.example",
        "Hi, Acme Health here, the role is at acmehealth.com/jobs/42",
        "Hi, Acme Health here, find me on linkedin.com/in/sam",
        "Hi, Acme Health here, see Acme.io for more.",
    ]:
        assert not rule(rules.check_message(bad, role), "no_links_or_emails").passed, bad


def test_tech_names_with_dots_are_not_links(sample_data):
    role = sample_data.role("role_backend_sr")
    for fine in [
        "Hi, Acme Health here. Your Node.js and ASP.NET work stood out. Chat?",
        "Hi, Acme Health here. You moved services to Python 3.12, e.g. on GCP. Chat?",
    ]:
        assert rule(rules.check_message(fine, role), "no_links_or_emails").passed, fine


def test_internal_ids_are_blocked(sample_data):
    role = sample_data.role("role_backend_sr")
    text = "Hi, Acme Health here about cand_001 and run_abc123, chat?"
    assert not rule(rules.check_message(text, role), "no_internal_ids").passed


def test_message_must_mention_the_role_or_company(sample_data):
    role = sample_data.role("role_backend_sr")
    text = "Hi Priya, I'm Sam. I think you would be a great fit. Open to a quick chat?"
    assert not rule(rules.check_message(text, role), "mentions_the_role").passed
    assert rule(
        rules.check_message(text + " Senior Backend Engineer", role), "mentions_the_role"
    ).passed
