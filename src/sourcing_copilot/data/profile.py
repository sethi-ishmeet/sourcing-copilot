"""Things we compute from a candidate record: years of experience, current job,
how old the profile is, and whether a quoted "proof" really appears in the profile.

Everything that depends on today's date takes `today` as an argument so tests are stable.
"""

from __future__ import annotations

import re
from datetime import date

from .models import Candidate, DoNotContactEntry, Job, SampleData

STALE_AFTER_DAYS = 365


def parse_month(value: str) -> date:
    year, month = value.split("-")
    return date(int(year), int(month), 1)


def months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def years_of_experience(candidate: Candidate, today: date) -> float:
    """From the earliest job start to the latest job end (or today), in years, 1 decimal."""
    if not candidate.experience:
        return 0.0
    first_start = min(parse_month(job.start_date) for job in candidate.experience)
    ends = [parse_month(job.end_date) if job.end_date else today for job in candidate.experience]
    last_end = max(ends)
    return round(months_between(first_start, last_end) / 12, 1)


def current_job(candidate: Candidate) -> Job | None:
    """The job with no end date; if none, the most recently started one."""
    if not candidate.experience:
        return None
    open_jobs = [job for job in candidate.experience if job.end_date is None]
    if open_jobs:
        return max(open_jobs, key=lambda job: job.start_date)
    return max(candidate.experience, key=lambda job: job.start_date)


def days_since_update(candidate: Candidate, today: date) -> int:
    return (today - candidate.profile_updated_at).days


def is_stale(candidate: Candidate, today: date) -> bool:
    return days_since_update(candidate, today) > STALE_AFTER_DAYS


def profile_text(candidate: Candidate) -> str:
    """Every piece of text on the profile, one item per line. Used for proof checks."""
    lines = [candidate.full_name, candidate.headline, candidate.location, candidate.about]
    lines.extend(candidate.skills)
    for job in candidate.experience:
        lines.append(f"{job.title} at {job.company}")
        lines.append(job.description)
    for edu in candidate.education:
        lines.append(f"{edu.degree} at {edu.school}".strip())
    return "\n".join(line for line in lines if line)


def normalize_text(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .,;:\"'()[]")


def quote_is_in_profile(quote: str, candidate: Candidate) -> bool:
    """True if `quote` appears verbatim in the profile, ignoring case, spacing and edge
    punctuation. Short quotes (under 3 characters) never count."""
    needle = normalize_text(quote)
    if len(needle) < 3:
        return False
    return needle in normalize_text(profile_text(candidate))


def normalize_url(url: str) -> str:
    return url.strip().lower().rstrip("/").replace("http://", "https://")


def find_do_not_contact(data: SampleData, candidate: Candidate) -> DoNotContactEntry | None:
    """Match by LinkedIn URL: the do-not-contact list comes from another system and
    does not know our candidate ids."""
    wanted = normalize_url(candidate.linkedin_url)
    return next((e for e in data.do_not_contact if normalize_url(e.linkedin_url) == wanted), None)


def profile_summary(candidate: Candidate, today: date) -> dict:
    """What the API and the copilot's profile tool return for a candidate."""
    job = current_job(candidate)
    return {
        "id": candidate.id,
        "full_name": candidate.full_name,
        "headline": candidate.headline,
        "location": candidate.location,
        "linkedin_url": candidate.linkedin_url,
        "current_title": job.title if job else None,
        "current_company": job.company if job else None,
        "years_of_experience": years_of_experience(candidate, today),
        "skills": list(candidate.skills),
        "experience": [job.model_dump() for job in candidate.experience],
        "education": [edu.model_dump() for edu in candidate.education],
        "profile_updated_at": candidate.profile_updated_at.isoformat(),
        "days_since_update": days_since_update(candidate, today),
        "is_stale": is_stale(candidate, today),
        # Written by the candidate. Treat as information about them, never as instructions.
        "about_written_by_candidate": candidate.about,
    }
