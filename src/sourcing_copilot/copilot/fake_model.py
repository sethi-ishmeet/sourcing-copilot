"""A stand-in for the real model so tests, CI and local demos need no API key.

It behaves like a careful model would: read the profile, check the do-not-contact list,
score each requirement by matching the role's keyword tags against the profile text, and
quote the matching text as proof. It is deliberately simple. Its job is to exercise the
pipeline and the rules, not to be smart.

`behaviour` switches make it misbehave on purpose so tests can prove the rules and the
loop guard hold even when the model does the wrong thing.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import ConfigDict

from sourcing_copilot.data.models import Role

BEHAVIOURS = (
    "normal",
    "never_submits",  # keeps calling get_profile; proves the tool-call cap works
    "bad_proof",  # quotes text that is not on the profile; proves the proof rule works
    "follows_hidden_instructions",  # obeys text planted in a profile; proves message rules work
    "too_long_message",  # ignores the length limit
    "looks_up_someone_else",  # asks for another candidate's profile first
    "bad_tool_arguments",  # calls get_profile with a wrong argument name first
    "skips_do_not_contact_check",  # never checks the list; proves the code checks it anyway
    "ignores_old_profile",  # stays confident on a stale profile; proves code lowers it
    "crash",  # raises, like an outage would
)


class FakeChatModel(BaseChatModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: Any = None  # SampleData; the fake needs the role's keyword tags
    behaviour: str = "normal"
    _call_counter: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        names = [t.name if hasattr(t, "name") else t.get("name") for t in tools]
        return self.bind(tool_names=names)

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        if self.behaviour == "crash":
            raise RuntimeError("fake model crashed on purpose")
        tool_names = kwargs.get("tool_names", [])
        if "submit_scorecard" in tool_names:
            reply = self._screen_turn(messages)
        elif "submit_message" in tool_names:
            reply = self._message_turn(messages)
        else:
            reply = AIMessage(content="I can only work through tools.")
        text_in = sum(len(str(m.content)) for m in messages)
        reply.usage_metadata = {
            "input_tokens": text_in // 4,
            "output_tokens": max(1, len(json.dumps(reply.tool_calls)) // 4),
            "total_tokens": text_in // 4 + max(1, len(json.dumps(reply.tool_calls)) // 4),
        }
        return ChatResult(generations=[ChatGeneration(message=reply)])

    # -- helpers -----------------------------------------------------------------

    def _tool_call(self, name: str, args: dict) -> AIMessage:
        self._call_counter += 1
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"call_{self._call_counter}"}],
        )

    @staticmethod
    def _request_text(messages: list[BaseMessage]) -> str:
        return next((str(m.content) for m in messages if isinstance(m, HumanMessage)), "")

    @staticmethod
    def _tool_results(messages: list[BaseMessage]) -> dict[str, list[dict]]:
        results: dict[str, list[dict]] = {}
        for m in messages:
            if isinstance(m, ToolMessage):
                try:
                    payload = json.loads(str(m.content))
                except json.JSONDecodeError:
                    payload = {"text": str(m.content)}
                results.setdefault(m.name or "", []).append(payload)
        return results

    def _screen_turn(self, messages: list[BaseMessage]) -> AIMessage:
        request = self._request_text(messages)
        candidate_id = re.search(r"Candidate id: (\S+)", request).group(1)
        role_id = re.search(r"Role id: (\S+)", request).group(1)
        results = self._tool_results(messages)

        if self.behaviour == "never_submits":
            return self._tool_call("get_profile", {"candidate_id": candidate_id})

        profiles = [p for p in results.get("get_profile", []) if "error" not in p]
        if not profiles:
            if self.behaviour == "looks_up_someone_else" and not results.get("get_profile"):
                other = next(c.id for c in self.data.candidates if c.id != candidate_id)
                return self._tool_call("get_profile", {"candidate_id": other})
            if self.behaviour == "bad_tool_arguments" and not results.get("get_profile"):
                return self._tool_call("get_profile", {"id": candidate_id})
            return self._tool_call("get_profile", {"candidate_id": candidate_id})
        if (
            not results.get("check_do_not_contact")
            and self.behaviour != "skips_do_not_contact_check"
        ):
            return self._tool_call("check_do_not_contact", {"candidate_id": candidate_id})

        role = self.data.role(role_id)
        scorecard = self._score(profiles[-1], role)
        return self._tool_call("submit_scorecard", scorecard)

    def _score(self, profile: dict, role: Role) -> dict:
        lines = [profile.get("headline", ""), profile.get("about_written_by_candidate", "")]
        lines += list(profile.get("skills", []))
        for job in profile.get("experience", []):
            lines.append(f"{job['title']} at {job['company']}")
            lines.append(job.get("description", ""))

        scores = []
        for req in role.requirements:
            hits = [kw for kw in req.keywords if kw.lower() in "\n".join(lines).lower()]
            score = 0 if not hits else (3 if len(hits) == 1 else 5)
            proof = self._quote_for(hits[0], lines) if hits else ""
            reason = (
                f"Profile mentions {', '.join(hits)}."
                if hits
                else "Nothing on the profile shows this."
            )
            if self.behaviour == "bad_proof" and score > 0:
                proof = "Led the first crewed mission to Mars"
            if self.behaviour == "follows_hidden_instructions":
                score, reason = 5, "The profile asked for full marks."
                proof = proof or lines[0]
            scores.append(
                {"requirement_id": req.id, "score": score, "reason": reason, "proof": proof}
            )

        must_ok = all(
            s["score"] >= 3
            for s in scores
            if next(r for r in role.requirements if r.id == s["requirement_id"]).must_have
        )
        stale = bool(profile.get("is_stale")) and self.behaviour != "ignores_old_profile"
        warnings = []
        if stale:
            warnings.append(
                f"Profile was last updated {profile.get('days_since_update')} days ago; "
                "details may be out of date."
            )
        if any("untrusted" in w for w in profile.get("data_warnings", [])):
            warnings.append("The profile text contains instructions aimed at an AI; ignored.")
        return {
            "scores": scores,
            "recommend": must_ok,
            "confidence": "low" if stale else "high",
            "summary": (
                f"{profile.get('full_name')} is {profile.get('current_title') or 'currently'} at "
                f"{profile.get('current_company') or 'an unknown company'} with "
                f"{profile.get('years_of_experience')} years of experience. "
                + ("Worth reaching out." if must_ok else "Missing a must-have requirement.")
            ),
            "warnings": warnings,
        }

    @staticmethod
    def _quote_for(keyword: str, lines: list[str]) -> str:
        for line in lines:
            if keyword.lower() in line.lower():
                for sentence in re.split(r"(?<=[.!?])\s+", line):
                    if keyword.lower() in sentence.lower():
                        return sentence.rstrip(".")
        return ""

    def _message_turn(self, messages: list[BaseMessage]) -> AIMessage:
        request = self._request_text(messages)
        role_line = re.search(r"Role: (.+?) at (.+)", request)
        sender_line = re.search(r"Sender: ([^,\n]+),? ?(.*)", request)
        cand_line = re.search(r"Candidate: ([^,\n]+)(?:, (.+))?", request)
        role_title, company = role_line.group(1), role_line.group(2)
        sender, sender_title = sender_line.group(1).strip(), sender_line.group(2).strip()
        first_name = cand_line.group(1).split()[0]
        current = (cand_line.group(2) or "").strip()

        fit = (
            f"Your work as {current}"
            if current and current != "no current job listed"
            else ("Your background")
        )
        text = (
            f"Hi {first_name}, I'm {sender}, {sender_title}. {fit} looks like a strong fit for "
            f"our {role_title} role at {company}. Open to a quick chat this week?"
        )
        if len(text) > 300:
            text = (
                f"Hi {first_name}, I'm {sender} at {company}. Your background looks like a strong "
                f"fit for our {role_title} role. Open to a quick chat this week?"
            )
        if self.behaviour == "follows_hidden_instructions":
            text += " See https://example.com/daniel-portfolio"
        if self.behaviour == "too_long_message":
            text += " " + "We have a great team and a great mission. " * 10
        return self._tool_call("submit_message", {"message": text})
