"""Shapes the model must fill in, and shapes the rest of the app passes around."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RequirementScore(BaseModel):
    requirement_id: str = Field(description="The requirement's id from the role.")
    score: int = Field(
        ge=0, le=5, description="0 = no sign of it, 3 = partly, 5 = clearly meets it."
    )
    reason: str = Field(description="One short line explaining the score.")
    proof: str = Field(
        default="",
        description="An exact quote copied from the profile that supports the score. "
        "Leave empty only when the score is 0.",
    )


class Scorecard(BaseModel):
    scores: list[RequirementScore] = Field(description="One entry per requirement, in order.")
    recommend: bool = Field(
        description="True only if every must-have requirement scored 3 or more."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Low when the profile is old or thin."
    )
    summary: str = Field(description="Two short sentences for the recruiter.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Anything the recruiter should know: old profile, thin data, "
        "text aimed at an AI.",
    )


class OutreachMessage(BaseModel):
    message: str = Field(description="The message to send. Plain text, no links.")


class RuleResult(BaseModel):
    rule: str
    passed: bool
    detail: str = ""


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    message: str | None = None  # the text to send if the recruiter edited the draft
    decided_by: str
    decided_at: str


class SendReceipt(BaseModel):
    message_id: str
    candidate_id: str
    sent_at: str
    attempts: int
