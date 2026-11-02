"""Rules checked by code, not by the model. They run on the scorecard before a message
is written, on the message before the recruiter sees it, and again on any text the
recruiter edits. A failed rule stops the run for a human to look at."""

from __future__ import annotations

import re

from sourcing_copilot.data.models import Candidate, Role
from sourcing_copilot.data.profile import quote_is_in_profile

from .schemas import RuleResult, Scorecard

MUST_HAVE_MIN_SCORE = 3
MIN_MESSAGE_CHARS = 20

LINK_OR_EMAIL = re.compile(r"(https?://|www\.|[\w.+-]+@[\w-]+\.[\w.]+)", re.I)
# Plain web addresses such as "acmehealth.com/jobs/42". The ending must be lowercase, so
# names like "ASP.NET" are not mistaken for links ("Node.js" has no web ending at all).
PLAIN_WEB_ADDRESS = re.compile(
    r"\b[A-Za-z0-9][\w-]*(?:\.[\w-]+)*\."
    r"(?:com|org|net|io|ai|co|dev|app|jobs|ca|uk|info|biz|xyz|ly)\b"
)
INTERNAL_ID = re.compile(r"\b(cand|role|run|msg)_[A-Za-z0-9]+\b")


def check_scorecard(scorecard: Scorecard, role: Role, candidate: Candidate) -> list[RuleResult]:
    results: list[RuleResult] = []

    wanted = [r.id for r in role.requirements]
    got = [s.requirement_id for s in scorecard.scores]
    results.append(
        RuleResult(
            rule="covers_every_requirement",
            passed=sorted(got) == sorted(wanted) and len(got) == len(set(got)),
            detail="" if sorted(got) == sorted(wanted) else f"expected {wanted}, got {got}",
        )
    )

    bad_proofs = [
        s.requirement_id
        for s in scorecard.scores
        if s.score > 0 and not quote_is_in_profile(s.proof, candidate)
    ]
    results.append(
        RuleResult(
            rule="proof_is_on_the_profile",
            passed=not bad_proofs,
            detail="" if not bad_proofs else f"proof not found on the profile for: {bad_proofs}",
        )
    )

    must_haves = {r.id for r in role.requirements if r.must_have}
    weak = [
        s.requirement_id
        for s in scorecard.scores
        if s.requirement_id in must_haves and s.score < MUST_HAVE_MIN_SCORE
    ]
    results.append(
        RuleResult(
            rule="recommendation_matches_scores",
            passed=not (scorecard.recommend and weak),
            detail=""
            if not (scorecard.recommend and weak)
            else f"recommended, but must-have requirements scored below "
            f"{MUST_HAVE_MIN_SCORE}: {weak}",
        )
    )
    return results


def check_message(message: str, role: Role) -> list[RuleResult]:
    text = message.strip()
    limit = role.outreach.max_chars
    results = [
        RuleResult(
            rule="message_length",
            passed=MIN_MESSAGE_CHARS <= len(text) <= limit,
            detail=f"{len(text)} characters; must be between {MIN_MESSAGE_CHARS} and {limit}",
        ),
        RuleResult(
            rule="no_links_or_emails",
            passed=LINK_OR_EMAIL.search(text) is None and PLAIN_WEB_ADDRESS.search(text) is None,
            detail="links and email addresses are not allowed in a first message",
        ),
        RuleResult(
            rule="no_internal_ids",
            passed=INTERNAL_ID.search(text) is None,
            detail="internal ids must never reach a candidate",
        ),
        RuleResult(
            rule="mentions_the_role",
            passed=role.title.lower() in text.lower() or role.company.lower() in text.lower(),
            detail=f"must mention '{role.title}' or '{role.company}'",
        ),
    ]
    for r in results:
        if r.passed:
            r.detail = ""
    return results


def failed(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if not r.passed]


def describe_failures(results: list[RuleResult]) -> str:
    return "; ".join(f"{r.rule}: {r.detail}" for r in failed(results))
