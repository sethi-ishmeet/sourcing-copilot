"""Data checks that run across the whole dataset, after each record passed its own shape
check. Errors mean a record must not be used; warnings are shown to the recruiter and
passed to the copilot as context.

Checks: required fields, date order, no future dates, unique ids and URLs, freshness,
suspicious candidate-written text, cross-source matching of the do-not-contact list,
and role shortlists that point at real candidates.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from .models import SampleData
from .profile import STALE_AFTER_DAYS, days_since_update, normalize_url, parse_month

SUSPICIOUS_PATTERNS = [
    re.compile(r"ignore (your|all|any|the|previous|prior|earlier)[^.]{0,40}instructions", re.I),
    re.compile(r"\bai (assistant|model|agent|system)\b", re.I),
    re.compile(r"skip (the )?approval", re.I),
    re.compile(r"(score|rate) (every|all|each) requirement", re.I),
]


class Problem(BaseModel):
    check: str
    severity: Literal["error", "warning"]
    source: Literal["candidates", "roles", "do_not_contact"]
    record_id: str
    message: str


def run_data_checks(data: SampleData, today: date) -> list[Problem]:
    problems: list[Problem] = []

    def add(check: str, severity: str, source: str, record_id: str, message: str) -> None:
        problems.append(
            Problem(
                check=check, severity=severity, source=source, record_id=record_id, message=message
            )
        )

    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for cand in data.candidates:
        if cand.id in seen_ids:
            add("duplicate_candidate", "error", "candidates", cand.id, "duplicate candidate id")
        seen_ids.add(cand.id)
        url = normalize_url(cand.linkedin_url)
        if url in seen_urls:
            add(
                "duplicate_candidate",
                "error",
                "candidates",
                cand.id,
                f"LinkedIn URL already used by another candidate: {cand.linkedin_url}",
            )
        seen_urls.add(url)

        if not cand.experience:
            add("missing_required_field", "error", "candidates", cand.id, "no work experience")
        for job in cand.experience:
            start = parse_month(job.start_date)
            end = parse_month(job.end_date) if job.end_date else None
            if end and end < start:
                add(
                    "bad_date",
                    "error",
                    "candidates",
                    cand.id,
                    f"{job.title} at {job.company} ends before it starts",
                )
            if start > today or (end and end > today):
                add(
                    "bad_date",
                    "error",
                    "candidates",
                    cand.id,
                    f"{job.title} at {job.company} has a date in the future",
                )

        if cand.profile_updated_at > today:
            add("bad_date", "error", "candidates", cand.id, "profile_updated_at is in the future")
        elif days_since_update(cand, today) > STALE_AFTER_DAYS:
            add(
                "stale_profile",
                "warning",
                "candidates",
                cand.id,
                f"profile last updated {days_since_update(cand, today)} days ago",
            )

        free_text = " ".join([cand.about, *(job.description for job in cand.experience)])
        if any(p.search(free_text) for p in SUSPICIOUS_PATTERNS):
            add(
                "suspicious_text",
                "warning",
                "candidates",
                cand.id,
                "profile text contains instructions aimed at an AI; it will be treated as "
                "untrusted",
            )

    known_urls = {normalize_url(c.linkedin_url) for c in data.candidates}
    for entry in data.do_not_contact:
        if normalize_url(entry.linkedin_url) not in known_urls:
            add(
                "do_not_contact_unmatched",
                "warning",
                "do_not_contact",
                entry.linkedin_url,
                "no candidate has this LinkedIn URL",
            )
        if entry.added_on > today:
            add(
                "bad_date",
                "error",
                "do_not_contact",
                entry.linkedin_url,
                "added_on is in the future",
            )

    seen_role_ids: set[str] = set()
    for role in data.roles:
        if role.id in seen_role_ids:
            add("duplicate_role", "error", "roles", role.id, "duplicate role id")
        seen_role_ids.add(role.id)
        if not role.requirements:
            add("role_without_requirements", "error", "roles", role.id, "role has no requirements")
        req_ids = [r.id for r in role.requirements]
        if len(req_ids) != len(set(req_ids)):
            add("duplicate_requirement", "error", "roles", role.id, "duplicate requirement id")
        for cand_id in role.shortlist:
            if cand_id not in seen_ids:
                add(
                    "shortlist_unknown_candidate",
                    "error",
                    "roles",
                    role.id,
                    f"shortlist points at unknown candidate {cand_id}",
                )

    return problems


def problems_for_candidate(problems: list[Problem], candidate_id: str) -> list[Problem]:
    return [p for p in problems if p.source == "candidates" and p.record_id == candidate_id]


def has_errors(problems: list[Problem]) -> bool:
    return any(p.severity == "error" for p in problems)
