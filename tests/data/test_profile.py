"""Numbers and facts the app derives from a profile are computed correctly."""

from __future__ import annotations

from datetime import date

from sourcing_copilot.data.models import DoNotContactEntry, Job
from sourcing_copilot.data.profile import (
    current_job,
    find_do_not_contact,
    is_stale,
    profile_summary,
    quote_is_in_profile,
    years_of_experience,
)
from tests.conftest import TODAY
from tests.data.helpers import make_candidate, make_data


def test_years_of_experience_spans_first_start_to_today_for_a_current_job(sample_data):
    priya = sample_data.candidate("cand_001")
    # Feb 2019 to Oct 2026 is 92 months.
    assert years_of_experience(priya, TODAY) == 7.7


def test_years_of_experience_stops_at_the_last_end_date_when_no_current_job():
    cand = make_candidate(
        experience=[
            Job(title="A", company="X", start_date="2015-01", end_date="2017-01"),
            Job(title="B", company="Y", start_date="2017-02", end_date="2020-01"),
        ]
    )
    assert years_of_experience(cand, TODAY) == 5.0


def test_no_experience_means_zero_years():
    assert years_of_experience(make_candidate(experience=[]), TODAY) == 0.0


def test_current_job_is_the_open_one(sample_data):
    job = current_job(sample_data.candidate("cand_003"))
    assert (job.title, job.company) == ("Staff Software Engineer", "Meridian Insurance")


def test_current_job_falls_back_to_latest_when_all_jobs_ended():
    cand = make_candidate(
        experience=[
            Job(title="Old", company="X", start_date="2015-01", end_date="2017-01"),
            Job(title="Newer", company="Y", start_date="2018-01", end_date="2020-01"),
        ]
    )
    assert current_job(cand).title == "Newer"


def test_stale_profile_is_flagged_after_a_year(sample_data):
    assert is_stale(sample_data.candidate("cand_005"), TODAY) is True
    assert is_stale(sample_data.candidate("cand_001"), TODAY) is False


def test_quote_check_ignores_case_spacing_and_edge_punctuation(sample_data):
    priya = sample_data.candidate("cand_001")
    assert quote_is_in_profile("FastAPI services on GCP Cloud Run", priya)
    assert quote_is_in_profile("  fastapi services on gcp cloud run.", priya)
    assert quote_is_in_profile("PostgreSQL", priya)


def test_quote_check_rejects_text_that_is_not_on_the_profile(sample_data):
    priya = sample_data.candidate("cand_001")
    assert not quote_is_in_profile("Led a team of 40 engineers at Google", priya)
    assert not quote_is_in_profile("", priya)
    assert not quote_is_in_profile("a", priya)


def test_do_not_contact_matches_by_url_ignoring_case_and_trailing_slash():
    cand = make_candidate(linkedin_url="https://www.linkedin.com/in/Test-Person-Sample/")
    entry = DoNotContactEntry(
        linkedin_url="https://www.linkedin.com/in/test-person-sample",
        reason="asked us to stop",
        added_on=date(2026, 1, 1),
    )
    data = make_data(candidates=[cand], do_not_contact=[entry])
    assert find_do_not_contact(data, cand) is entry


def test_do_not_contact_returns_none_for_everyone_else(sample_data):
    assert find_do_not_contact(sample_data, sample_data.candidate("cand_001")) is None
    blocked = find_do_not_contact(sample_data, sample_data.candidate("cand_003"))
    assert blocked is not None and blocked.reason == "Asked us not to contact them again"


def test_profile_summary_presents_computed_fields(sample_data):
    summary = profile_summary(sample_data.candidate("cand_005"), TODAY)
    assert summary["current_title"] == "Backend Engineer"
    assert summary["current_company"] == "Harbour Clinic Software"
    assert summary["years_of_experience"] == 8.8
    assert summary["days_since_update"] == 881
    assert summary["is_stale"] is True
    assert summary["about_written_by_candidate"].startswith("Python backend engineer")
