"""The copilot's steps, wired together as a LangGraph graph.

    screen -> check_scorecard -> write_message -> check_message
        -> wait_for_approval -> send -> finish

Any step can route straight to `finish` when there is nothing more to do (not recommended,
on the do-not-contact list, failed a rule, or an error). `wait_for_approval` pauses the
graph with an interrupt; the checkpointer saves the state, and `decide()` resumes it.

Everything the model can do goes through `screen` and `write_message`. Everything that
matters for safety (rules, do-not-contact, sending) is plain code in the other steps.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from sourcing_copilot.config import Settings
from sourcing_copilot.data.checks import problems_for_candidate, run_data_checks
from sourcing_copilot.data.models import SampleData
from sourcing_copilot.data.profile import find_do_not_contact, is_stale
from sourcing_copilot.logs import log_event

from . import rules
from .linkedin import PretendLinkedIn, SendFailed
from .prompts import SCREEN_SYSTEM, WRITE_MESSAGE_SYSTEM, message_request, screen_request
from .schemas import OutreachMessage, Scorecard
from .state import ScreeningState, StepRecord
from .tools import make_lookup_tools, submit_message_tool, submit_scorecard_tool

log = logging.getLogger("copilot")

MAX_MODEL_TURNS = 10  # a second guard on top of the tool-call cap
MAX_SUBMIT_ATTEMPTS = 2  # how many times the model may hand in something that fails checks
SEND_ATTEMPTS = 3


class ModelError(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Copilot:
    def __init__(
        self,
        data: SampleData,
        model: BaseChatModel,
        linkedin: PretendLinkedIn,
        settings: Settings,
        checkpointer: BaseCheckpointSaver | None = None,
        today: Callable[[], date] | None = None,
        send_retry_wait_seconds: float = 0.5,
    ) -> None:
        self.data = data
        self.model = model
        self.linkedin = linkedin
        self.settings = settings
        self.checkpointer = checkpointer or InMemorySaver()
        self.today = today or (lambda: datetime.now(UTC).date())
        self.send_retry_wait_seconds = send_retry_wait_seconds
        self.problems = run_data_checks(data, self.today())
        self.graph = self.build_graph(self.checkpointer)

    # -- public API -------------------------------------------------------------

    def start(self, run_id: str, role_id: str, candidate_id: str) -> ScreeningState:
        """Run until the copilot needs a human or has nothing more to do."""
        first: ScreeningState = {
            "run_id": run_id,
            "role_id": role_id,
            "candidate_id": candidate_id,
            "status": "screening",
            "messages": [],
            "profile": None,
            "contact_allowed": None,
            "contact_reason": None,
            "data_warnings": [],
            "scorecard": None,
            "draft_message": None,
            "rule_results": [],
            "decision": None,
            "final_message": None,
            "send_receipt": None,
            "error": None,
            "tool_calls_made": 0,
            "steps": [],
        }
        self.graph.invoke(first, self._config(run_id))
        return self.state(run_id)

    def decide(
        self, run_id: str, action: str, decided_by: str, message: str | None = None
    ) -> ScreeningState:
        """Resume a paused run with the recruiter's decision."""
        decision = {
            "action": action,
            "message": message,
            "decided_by": decided_by,
            "decided_at": _now_iso(),
        }
        self.graph.invoke(Command(resume=decision), self._config(run_id))
        return self.state(run_id)

    def state(self, run_id: str) -> ScreeningState:
        return self.graph.get_state(self._config(run_id)).values

    def is_waiting(self, run_id: str) -> bool:
        return bool(self.graph.get_state(self._config(run_id)).next)

    @staticmethod
    def _config(run_id: str) -> dict:
        return {"configurable": {"thread_id": run_id}}

    # -- graph --------------------------------------------------------------------

    def build_graph(self, checkpointer: BaseCheckpointSaver | None):
        """Wire the steps together. The app passes its SQLite checkpointer; LangGraph
        Studio passes None because the dev server brings its own."""
        g = StateGraph(ScreeningState)
        g.add_node("screen", self.screen)
        g.add_node("check_scorecard", self.check_scorecard)
        g.add_node("write_message", self.write_message)
        g.add_node("check_message", self.check_message)
        g.add_node("wait_for_approval", self.wait_for_approval)
        g.add_node("send", self.send)
        g.add_node("finish", self.finish)

        def still_going(next_step: str):
            return lambda state: next_step if state["status"] == "screening" else "finish"

        g.add_edge(START, "screen")
        g.add_conditional_edges("screen", still_going("check_scorecard"))
        g.add_conditional_edges("check_scorecard", still_going("write_message"))
        g.add_conditional_edges("write_message", still_going("check_message"))
        g.add_conditional_edges(
            "check_message",
            lambda s: "wait_for_approval" if s["status"] == "awaiting_approval" else "finish",
        )
        g.add_conditional_edges(
            "wait_for_approval",
            lambda s: "send" if s["decision"]["action"] == "approve" else "finish",
        )
        g.add_edge("send", "finish")
        g.add_edge("finish", END)
        return g.compile(checkpointer=checkpointer)

    # -- steps --------------------------------------------------------------------

    def screen(self, state: ScreeningState) -> dict:
        """Let the model read the profile and the do-not-contact list, then hand in a
        scorecard. The model may call at most `max_tool_calls` tools."""
        role = self.data.role(state["role_id"])
        candidate = self.data.candidate(state["candidate_id"])
        if role is None or candidate is None:
            return self._fail(
                state, [], f"unknown role {state['role_id']} or candidate {state['candidate_id']}"
            )

        data_warnings = [p.message for p in problems_for_candidate(self.problems, candidate.id)]
        lookup = make_lookup_tools(self.data, self.today(), candidate.id, data_warnings)
        model = self.model.bind_tools([*lookup.values(), submit_scorecard_tool])
        messages: list[BaseMessage] = [
            SystemMessage(SCREEN_SYSTEM),
            HumanMessage(screen_request(role, candidate.id)),
        ]
        steps: list[StepRecord] = []
        update: dict[str, Any] = {
            "data_warnings": data_warnings,
            "profile": None,
            "contact_allowed": None,
            "contact_reason": None,
            "tool_calls_made": 0,
        }
        submit_attempts = 0
        last_problem = ""

        for _turn in range(MAX_MODEL_TURNS):
            try:
                reply = self._call_model(model, messages, "ask model to screen", steps, state)
            except ModelError as err:
                return self._fail(state, steps, str(err), update)
            messages.append(reply)

            if not reply.tool_calls:
                messages.append(
                    HumanMessage("Please use the tools. When done, call submit_scorecard.")
                )
                continue

            for call in reply.tool_calls:
                if call["name"] == "submit_scorecard":
                    submit_attempts += 1
                    scorecard, problem = self._parse_scorecard(call["args"], role, candidate)
                    if scorecard is not None:
                        steps.append(
                            self._step(
                                state["run_id"], "scorecard accepted", {"attempt": submit_attempts}
                            )
                        )
                        update["scorecard"] = scorecard.model_dump()
                        return {
                            **update,
                            "messages": messages,
                            "steps": steps,
                            "status": "screening",
                        }
                    last_problem = problem
                    steps.append(
                        self._step(
                            state["run_id"],
                            "scorecard rejected",
                            {"attempt": submit_attempts, "problem": problem},
                            status="error",
                        )
                    )
                    if submit_attempts >= MAX_SUBMIT_ATTEMPTS:
                        update["scorecard"] = call["args"]
                        return self._stop(
                            state,
                            steps,
                            "needs_review",
                            f"scorecard failed checks after {submit_attempts} attempts: "
                            f"{last_problem}",
                            update,
                        )
                    messages.append(
                        ToolMessage(
                            content=f"Not accepted: {problem}. Fix it and call "
                            "submit_scorecard again.",
                            tool_call_id=call["id"],
                            name="submit_scorecard",
                        )
                    )
                    continue

                if update["tool_calls_made"] >= self.settings.max_tool_calls:
                    return self._fail(
                        state,
                        steps,
                        f"stopped after {self.settings.max_tool_calls} tool calls without "
                        "a scorecard",
                        update,
                    )
                update["tool_calls_made"] += 1
                result_text, step = self._run_tool(state["run_id"], lookup, call)
                steps.append(step)
                messages.append(
                    ToolMessage(content=result_text, tool_call_id=call["id"], name=call["name"])
                )
                result = json.loads(result_text)
                if call["name"] == "get_profile" and "error" not in result:
                    update["profile"] = result
                if call["name"] == "check_do_not_contact" and "error" not in result:
                    update["contact_allowed"] = result["allowed"]
                    update["contact_reason"] = result["reason"]
                    if not result["allowed"]:
                        # Stop here: no point scoring someone we are not allowed to message.
                        return self._stop(
                            state,
                            steps,
                            "do_not_contact",
                            f"on the do-not-contact list: {result['reason']}",
                            update,
                            messages,
                        )

        return self._fail(
            state,
            steps,
            f"model did not hand in a scorecard within {MAX_MODEL_TURNS} turns",
            update,
        )

    def check_scorecard(self, state: ScreeningState) -> dict:
        """Code checks the scorecard regardless of what the model said."""
        role = self.data.role(state["role_id"])
        candidate = self.data.candidate(state["candidate_id"])
        scorecard = Scorecard(**state["scorecard"])
        results = rules.check_scorecard(scorecard, role, candidate)
        update: dict[str, Any] = {"rule_results": [r.model_dump() for r in results]}
        warnings = list(state.get("data_warnings", []))

        entry = find_do_not_contact(self.data, candidate)
        if entry is not None:
            return self._stop(
                state,
                [self._step(state["run_id"], "check scorecard", {"do_not_contact": entry.reason})],
                "do_not_contact",
                f"on the do-not-contact list: {entry.reason}",
                {**update, "contact_allowed": False, "contact_reason": entry.reason},
            )

        if is_stale(candidate, self.today()) and scorecard.confidence != "low":
            scorecard.confidence = "low"
            warnings.append("Confidence lowered to low because the profile is over a year old.")
        update["scorecard"] = scorecard.model_dump()
        update["data_warnings"] = warnings

        failed = rules.failed(results)
        step = self._step(
            state["run_id"],
            "check scorecard",
            {"rules": [r.model_dump() for r in results]},
            status="error" if failed else "ok",
        )
        if failed:
            return self._stop(
                state, [step], "needs_review", rules.describe_failures(results), update
            )
        if not scorecard.recommend:
            return self._stop(state, [step], "not_recommended", None, update)
        return {**update, "steps": [step], "status": "screening"}

    def write_message(self, state: ScreeningState) -> dict:
        """Ask the model for a message. If it breaks a rule, show it the rule and let it
        try once more."""
        role = self.data.role(state["role_id"])
        model = self.model.bind_tools([submit_message_tool])
        messages: list[BaseMessage] = [
            SystemMessage(WRITE_MESSAGE_SYSTEM),
            HumanMessage(message_request(role, state["profile"] or {}, state["scorecard"])),
        ]
        steps: list[StepRecord] = []
        draft = None
        problem = ""
        last_results: list[rules.RuleResult] = []
        for attempt in range(1, MAX_SUBMIT_ATTEMPTS + 1):
            try:
                reply = self._call_model(
                    model, messages, "ask model to write message", steps, state
                )
            except ModelError as err:
                return self._fail(state, steps, str(err))
            messages.append(reply)
            call = next((c for c in reply.tool_calls if c["name"] == "submit_message"), None)
            if call is None:
                problem = "the model did not call submit_message"
                messages.append(HumanMessage("Call submit_message with the message text."))
                continue
            try:
                draft = OutreachMessage(**call["args"]).message.strip()
            except ValidationError as err:
                problem = f"invalid message payload: {err.errors()[0]['msg']}"
                messages.append(
                    ToolMessage(
                        content=f"Not accepted: {problem}",
                        tool_call_id=call["id"],
                        name="submit_message",
                    )
                )
                continue
            results = rules.check_message(draft, role)
            last_results = results
            if not rules.failed(results):
                steps.append(
                    self._step(
                        state["run_id"], "draft accepted", {"attempt": attempt, "chars": len(draft)}
                    )
                )
                return {"draft_message": draft, "steps": steps, "status": "screening"}
            problem = rules.describe_failures(results)
            steps.append(
                self._step(
                    state["run_id"],
                    "draft rejected",
                    {"attempt": attempt, "problem": problem},
                    status="error",
                )
            )
            messages.append(
                ToolMessage(
                    content=f"Not accepted: {problem}. Rewrite it and call submit_message again.",
                    tool_call_id=call["id"],
                    name="submit_message",
                )
            )
        return self._stop(
            state,
            steps,
            "needs_review",
            f"message failed checks after {MAX_SUBMIT_ATTEMPTS} attempts: {problem}",
            {
                "draft_message": draft,
                "rule_results": list(state.get("rule_results", []))
                + [r.model_dump() for r in last_results],
            },
        )

    def check_message(self, state: ScreeningState) -> dict:
        """The gate before a human sees the draft. write_message already tried to fix
        problems; this is the final say."""
        role = self.data.role(state["role_id"])
        results = rules.check_message(state["draft_message"] or "", role)
        all_results = list(state.get("rule_results", [])) + [r.model_dump() for r in results]
        failed = rules.failed(results)
        step = self._step(
            state["run_id"],
            "check message",
            {"rules": [r.model_dump() for r in results]},
            status="error" if failed else "ok",
        )
        if failed:
            return self._stop(
                state,
                [step],
                "needs_review",
                rules.describe_failures(results),
                {"rule_results": all_results},
            )
        return {"rule_results": all_results, "steps": [step], "status": "awaiting_approval"}

    def wait_for_approval(self, state: ScreeningState) -> dict:
        """Pause here. The graph stops, the state is saved, and nothing happens until
        `decide()` is called with the recruiter's answer."""
        decision = interrupt(
            {
                "run_id": state["run_id"],
                "candidate_id": state["candidate_id"],
                "draft_message": state["draft_message"],
                "summary": (state.get("scorecard") or {}).get("summary"),
            }
        )
        edited = (decision.get("message") or "").strip()
        final = edited or state["draft_message"]
        step = self._step(
            state["run_id"],
            "wait for approval",
            {
                "action": decision["action"],
                "decided_by": decision["decided_by"],
                "edited": bool(edited) and edited != state["draft_message"],
            },
        )
        if decision["action"] == "approve":
            return {
                "decision": decision,
                "final_message": final,
                "steps": [step],
                "status": "screening",
            }
        return {"decision": decision, "final_message": None, "steps": [step], "status": "rejected"}

    def send(self, state: ScreeningState) -> dict:
        """Send through the pretend LinkedIn, retrying with the same idempotency key so a
        dropped connection never turns into a duplicate message."""
        role = self.data.role(state["role_id"])
        candidate = self.data.candidate(state["candidate_id"])
        message = state["final_message"] or ""

        # Last line of defence, in case someone resumes the graph without going through the API.
        if find_do_not_contact(self.data, candidate) is not None:
            return self._stop(
                state,
                [
                    self._step(
                        state["run_id"], "send", {"blocked": "do_not_contact"}, status="error"
                    )
                ],
                "do_not_contact",
                "on the do-not-contact list",
                {},
            )
        results = rules.check_message(message, role)
        if rules.failed(results):
            return self._stop(
                state,
                [
                    self._step(
                        state["run_id"],
                        "send",
                        {"blocked": rules.describe_failures(results)},
                        status="error",
                    )
                ],
                "needs_review",
                f"edited message failed checks: {rules.describe_failures(results)}",
                {},
            )

        steps: list[StepRecord] = []
        last_error = ""
        for attempt in range(1, SEND_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                receipt = self.linkedin.send(candidate.id, message, idempotency_key=state["run_id"])
            except SendFailed as err:
                last_error = str(err)
                steps.append(
                    self._step(
                        state["run_id"],
                        "send",
                        {"attempt": attempt, "error": last_error},
                        status="error",
                        started=started,
                    )
                )
                if attempt < SEND_ATTEMPTS:
                    time.sleep(self.send_retry_wait_seconds * attempt)
                continue
            steps.append(
                self._step(
                    state["run_id"],
                    "send",
                    {"attempt": attempt, "receipt": receipt.model_dump()},
                    started=started,
                )
            )
            return {"send_receipt": receipt.model_dump(), "steps": steps, "status": "sent"}
        return self._fail(
            state, steps, f"could not send after {SEND_ATTEMPTS} attempts: {last_error}"
        )

    def finish(self, state: ScreeningState) -> dict:
        tokens_in = sum(s.get("tokens_in", 0) for s in state.get("steps", []))
        tokens_out = sum(s.get("tokens_out", 0) for s in state.get("steps", []))
        step = self._step(
            state["run_id"],
            "finish",
            {
                "status": state["status"],
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "error": state.get("error"),
            },
        )
        log_event(
            log,
            "screening_finished",
            run_id=state["run_id"],
            status=state["status"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            error=state.get("error"),
        )
        return {"steps": [step]}

    # -- helpers --------------------------------------------------------------------

    def _call_model(self, model, messages, step_name, steps, state) -> AIMessage:
        started = time.perf_counter()
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                reply = model.invoke(messages)
                break
            except Exception as err:  # noqa: BLE001 - any model/provider error is handled the same way
                last_err = err
                log_event(
                    log,
                    "model_call_failed",
                    logging.WARNING,
                    run_id=state.get("run_id"),
                    step=step_name,
                    attempt=attempt + 1,
                    error=str(err),
                )
        else:
            steps.append(
                self._step(
                    state["run_id"],
                    step_name,
                    {"error": str(last_err)},
                    status="error",
                    started=started,
                )
            )
            raise ModelError(f"model call failed twice: {last_err}")
        usage = reply.usage_metadata or {}
        steps.append(
            self._step(
                state["run_id"],
                step_name,
                {
                    "tool_calls": [
                        {"name": c["name"], "args": c["args"]} for c in reply.tool_calls
                    ],
                    "text": str(reply.text if isinstance(reply.text, str) else reply.content)[:500],
                },
                started=started,
                tokens_in=usage.get("input_tokens", 0),
                tokens_out=usage.get("output_tokens", 0),
            )
        )
        return reply

    @staticmethod
    def _run_tool(run_id, lookup, call) -> tuple[str, StepRecord]:
        started = time.perf_counter()
        tool = lookup.get(call["name"])
        if tool is None:
            result = json.dumps({"error": f"unknown tool {call['name']}"})
        else:
            result = tool.invoke(call["args"])
        payload = json.loads(result)
        step = Copilot._step(
            run_id,
            f"tool: {call['name']}",
            {"input": call["args"], "output": payload},
            status="error" if "error" in payload else "ok",
            started=started,
        )
        return result, step

    @staticmethod
    def _parse_scorecard(args, role, candidate) -> tuple[Scorecard | None, str | None]:
        try:
            scorecard = Scorecard(**args)
        except ValidationError as err:
            first = err.errors()[0]
            return None, f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        failed = rules.failed(rules.check_scorecard(scorecard, role, candidate))
        # Only the fixable problems are sent back to the model here; the rest are judged later.
        fixable = [
            r for r in failed if r.rule in {"covers_every_requirement", "proof_is_on_the_profile"}
        ]
        if fixable:
            return None, rules.describe_failures(fixable)
        return scorecard, None

    @staticmethod
    def _step(
        run_id, name, details, status="ok", started=None, tokens_in=0, tokens_out=0
    ) -> StepRecord:
        ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        record: StepRecord = {
            "name": name,
            "status": status,
            "started_at": _now_iso(),
            "ms": ms,
            "details": details,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
        log_event(
            log,
            "step",
            run_id=run_id,
            step=name,
            status=status,
            ms=ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return record

    def _stop(self, state, steps, status, error, update=None, messages=None) -> dict:
        out = {**(update or {}), "steps": steps, "status": status, "error": error}
        if messages is not None:
            out["messages"] = messages
        return out

    def _fail(self, state, steps, error, update=None) -> dict:
        log_event(log, "screening_failed", logging.ERROR, run_id=state.get("run_id"), error=error)
        return self._stop(state, steps, "failed", error, update)
