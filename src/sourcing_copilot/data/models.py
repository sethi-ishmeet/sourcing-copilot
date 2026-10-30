"""Shapes of the three sources: candidates, roles, and the do-not-contact list.

Pydantic rejects records with missing or wrongly typed fields at load time. Checks that
need the whole dataset (duplicates, cross-source matches, freshness) live in checks.py.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class Job(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    start_date: str  # "YYYY-MM"
    end_date: str | None = None  # None means this is the current job
    description: str = ""

    @field_validator("start_date", "end_date")
    @classmethod
    def month_format(cls, value: str | None) -> str | None:
        if value is not None and not MONTH_PATTERN.match(value):
            raise ValueError(f"expected YYYY-MM, got {value!r}")
        return value


class Education(BaseModel):
    school: str
    degree: str = ""
    end_year: int | None = None


class Candidate(BaseModel):
    id: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    headline: str = Field(min_length=1)
    location: str = ""
    linkedin_url: str = Field(min_length=1)
    about: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[Job] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    profile_updated_at: date


class Requirement(BaseModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    must_have: bool = False
    # Tags from the ATS. The fake model matches on these; the real model reads `text`.
    keywords: list[str] = Field(default_factory=list)


class OutreachSettings(BaseModel):
    sender_name: str
    sender_title: str = ""
    max_chars: int = Field(default=300, gt=0)


class Role(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str = ""
    description: str = ""
    requirements: list[Requirement] = Field(default_factory=list)
    outreach: OutreachSettings
    shortlist: list[str] = Field(default_factory=list)


class DoNotContactEntry(BaseModel):
    linkedin_url: str = Field(min_length=1)
    reason: str = ""
    added_on: date


class SampleData(BaseModel):
    candidates: list[Candidate]
    roles: list[Role]
    do_not_contact: list[DoNotContactEntry]

    def candidate(self, candidate_id: str) -> Candidate | None:
        return next((c for c in self.candidates if c.id == candidate_id), None)

    def role(self, role_id: str) -> Role | None:
        return next((r for r in self.roles if r.id == role_id), None)
