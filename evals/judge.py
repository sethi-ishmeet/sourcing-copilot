"""Optional model-based scoring of the draft message. It never gates a run; it is
reported next to the deterministic results so a human can spot quality drift."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from sourcing_copilot.data.models import Role


class MessageVerdict(BaseModel):
    score: int = Field(
        ge=1, le=5, description="1 = would embarrass the recruiter, 5 = ready to send"
    )
    reasons: str = Field(description="One or two short sentences.")


JUDGE_PROMPT = """You are reviewing a recruiter's first message to a candidate.
Score it from 1 to 5 using these questions:
- Is it specific to this candidate, using facts from the scorecard, not generic praise?
- Does it name the role and the company?
- Is the tone friendly and professional, and is it short?
- Does it avoid claims that are not supported by the scorecard?

Role: {role_title} at {company}
Scorecard summary: {summary}
Reasons the copilot gave: {reasons}

Message:
{message}
"""


def judge_message(model: BaseChatModel, role: Role, scorecard: dict, message: str) -> dict:
    prompt = JUDGE_PROMPT.format(
        role_title=role.title,
        company=role.company,
        summary=scorecard.get("summary", ""),
        reasons="; ".join(f"{s['requirement_id']}: {s['reason']}" for s in scorecard["scores"]),
        message=message,
    )
    try:
        verdict = model.with_structured_output(MessageVerdict).invoke(prompt)
        return {"score": verdict.score, "reasons": verdict.reasons}
    except Exception as err:  # noqa: BLE001 - the judge must never break the eval run
        return {"score": None, "reasons": f"judge failed: {err}"}
