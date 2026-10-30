"""Everything the copilot knows about one screening lives in this state. LangGraph
checkpoints it after every step, which is what lets a run pause for approval and resume
later, even after the server restarts."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# Where a screening can end up. "screening" is the only in-progress status.
STATUSES = (
    "screening",
    "awaiting_approval",
    "sent",
    "rejected",
    "not_recommended",
    "do_not_contact",
    "needs_review",
    "failed",
)


class StepRecord(TypedDict, total=False):
    seq: int
    name: str
    status: str  # "ok" or "error"
    started_at: str
    ms: int
    details: dict[str, Any]
    tokens_in: int
    tokens_out: int


class ScreeningState(TypedDict, total=False):
    run_id: str
    role_id: str
    candidate_id: str
    status: str
    messages: Annotated[list[AnyMessage], add_messages]
    profile: dict[str, Any] | None
    contact_allowed: bool | None
    contact_reason: str | None
    data_warnings: list[str]
    scorecard: dict[str, Any] | None
    draft_message: str | None
    rule_results: list[dict[str, Any]]
    decision: dict[str, Any] | None
    final_message: str | None
    send_receipt: dict[str, Any] | None
    error: str | None
    tool_calls_made: int
    steps: Annotated[list[StepRecord], operator.add]
