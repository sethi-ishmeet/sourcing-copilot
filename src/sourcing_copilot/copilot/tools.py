"""Tools the model can call. All of them are read-only. Sending a message is not a tool
the model can see; it happens in code after a human approves.

Each run gets its own tools, locked to the candidate being screened, so the model cannot
read other people's profiles even if it asks."""

from __future__ import annotations

import json
from datetime import date

from langchain_core.tools import BaseTool, StructuredTool

from sourcing_copilot.data.models import SampleData
from sourcing_copilot.data.profile import find_do_not_contact, profile_summary

from .schemas import OutreachMessage, Scorecard


def make_lookup_tools(
    data: SampleData, today: date, allowed_candidate_id: str, data_warnings: list[str]
) -> dict[str, BaseTool]:
    def get_profile(candidate_id: str) -> str:
        """Read the candidate's profile: headline, skills, work history, education, years of
        experience, and how long ago the profile was last updated."""
        if candidate_id != allowed_candidate_id:
            return json.dumps(
                {"error": f"not allowed: this screening may only look up {allowed_candidate_id}"}
            )
        candidate = data.candidate(candidate_id)
        if candidate is None:
            return json.dumps({"error": f"no candidate with id {candidate_id}"})
        profile = profile_summary(candidate, today)
        profile["data_warnings"] = list(data_warnings)
        return json.dumps(profile)

    def check_do_not_contact(candidate_id: str) -> str:
        """Check whether we are allowed to message this candidate. Some people have asked
        us not to contact them."""
        if candidate_id != allowed_candidate_id:
            return json.dumps(
                {"error": f"not allowed: this screening may only check {allowed_candidate_id}"}
            )
        candidate = data.candidate(candidate_id)
        if candidate is None:
            return json.dumps({"error": f"no candidate with id {candidate_id}"})
        entry = find_do_not_contact(data, candidate)
        return json.dumps(
            {
                "candidate_id": candidate_id,
                "allowed": entry is None,
                "reason": entry.reason if entry else "not on the do-not-contact list",
            }
        )

    tools = [
        StructuredTool.from_function(get_profile),
        StructuredTool.from_function(check_do_not_contact),
    ]
    return {t.name: t for t in tools}


def _received(**_: object) -> str:
    return "received"


# These two tools do nothing when called. They exist so the model hands back a filled-in
# Scorecard or OutreachMessage in a shape we can validate, instead of free text.
submit_scorecard_tool = StructuredTool.from_function(
    func=_received,
    name="submit_scorecard",
    description="Hand in the finished scorecard for this candidate.",
    args_schema=Scorecard,
)

submit_message_tool = StructuredTool.from_function(
    func=_received,
    name="submit_message",
    description="Hand in the outreach message.",
    args_schema=OutreachMessage,
)
