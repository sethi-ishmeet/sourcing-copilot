"""Small builders so data tests can describe a bad record in one line."""

from __future__ import annotations

from datetime import date

from sourcing_copilot.data.models import (
    Candidate,
    DoNotContactEntry,
    Job,
    OutreachSettings,
    Requirement,
    Role,
    SampleData,
)


def make_candidate(**overrides) -> Candidate:
    fields = dict(
        id="cand_test",
        full_name="Test Person",
        headline="Backend Engineer at Example Co",
        location="Toronto, Canada",
        linkedin_url="https://www.linkedin.com/in/test-person-sample",
        about="Python backend engineer.",
        skills=["Python", "PostgreSQL"],
        experience=[
            Job(
                title="Backend Engineer",
                company="Example Co",
                start_date="2021-01",
                end_date=None,
                description="Python services on GCP.",
            )
        ],
        education=[],
        profile_updated_at=date(2026, 9, 1),
    )
    fields.update(overrides)
    return Candidate(**fields)


def make_role(**overrides) -> Role:
    fields = dict(
        id="role_test",
        title="Backend Engineer",
        company="Example Co",
        requirements=[
            Requirement(id="python", text="Python backend", must_have=True, keywords=["python"]),
        ],
        outreach=OutreachSettings(sender_name="Sam", max_chars=300),
        shortlist=["cand_test"],
    )
    fields.update(overrides)
    return Role(**fields)


def make_data(
    candidates: list[Candidate] | None = None,
    roles: list[Role] | None = None,
    do_not_contact: list[DoNotContactEntry] | None = None,
) -> SampleData:
    return SampleData(
        candidates=candidates if candidates is not None else [make_candidate()],
        roles=roles if roles is not None else [make_role()],
        do_not_contact=do_not_contact or [],
    )
