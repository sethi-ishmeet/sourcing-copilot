"""The endpoints. Thin on purpose: check the request, call the copilot or the store,
shape the answer. Anything clever lives in the copilot or the data package."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from sourcing_copilot.copilot import rules
from sourcing_copilot.data.checks import has_errors, problems_for_candidate
from sourcing_copilot.data.profile import profile_summary
from sourcing_copilot.logs import log_event

from .auth import User, require_recruiter, require_viewer

log = logging.getLogger("api")
router = APIRouter(prefix="/api")


class StartScreeningRequest(BaseModel):
    candidate_id: str = Field(min_length=1)


class DecisionRequest(BaseModel):
    action: Literal["approve", "reject"]
    message: str | None = Field(default=None, max_length=2000)


# -- read-only -----------------------------------------------------------------------


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    return {"status": "ok", "model": request.app.state.settings.model}


@router.get("/data-checks")
def data_checks(request: Request, _: User = Depends(require_viewer)) -> dict[str, Any]:
    problems = request.app.state.copilot.problems
    return {
        "errors": sum(1 for p in problems if p.severity == "error"),
        "warnings": sum(1 for p in problems if p.severity == "warning"),
        "problems": [p.model_dump() for p in problems],
    }


@router.get("/roles")
def list_roles(request: Request, _: User = Depends(require_viewer)) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "title": r.title,
            "company": r.company,
            "location": r.location,
            "shortlist_size": len(r.shortlist),
        }
        for r in request.app.state.data.roles
    ]


@router.get("/roles/{role_id}")
def get_role(role_id: str, request: Request, _: User = Depends(require_viewer)) -> dict[str, Any]:
    app = request.app
    role = app.state.data.role(role_id)
    if role is None:
        raise HTTPException(status_code=404, detail=f"no role with id {role_id}")
    latest = app.state.store.latest_for_role(role_id)
    candidates = []
    for candidate_id in role.shortlist:
        candidate = app.state.data.candidate(candidate_id)
        if candidate is None:
            continue
        summary = profile_summary(candidate, app.state.today())
        candidates.append(
            {
                "id": candidate.id,
                "full_name": summary["full_name"],
                "headline": summary["headline"],
                "location": summary["location"],
                "current_title": summary["current_title"],
                "current_company": summary["current_company"],
                "years_of_experience": summary["years_of_experience"],
                "is_stale": summary["is_stale"],
                "data_warnings": [
                    p.message
                    for p in problems_for_candidate(app.state.copilot.problems, candidate.id)
                ],
                "latest_screening": latest.get(candidate.id),
            }
        )
    return {
        "id": role.id,
        "title": role.title,
        "company": role.company,
        "location": role.location,
        "description": role.description,
        "requirements": [
            {"id": r.id, "text": r.text, "must_have": r.must_have} for r in role.requirements
        ],
        "outreach": role.outreach.model_dump(),
        "candidates": candidates,
    }


@router.get("/candidates/{candidate_id}")
def get_candidate(
    candidate_id: str, request: Request, _: User = Depends(require_viewer)
) -> dict[str, Any]:
    app = request.app
    candidate = app.state.data.candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"no candidate with id {candidate_id}")
    summary = profile_summary(candidate, app.state.today())
    summary["data_warnings"] = [
        p.message for p in problems_for_candidate(app.state.copilot.problems, candidate.id)
    ]
    return summary


@router.get("/screenings/{run_id}")
def get_screening(
    run_id: str, request: Request, _: User = Depends(require_viewer)
) -> dict[str, Any]:
    return _screening_response(request, run_id)


@router.get("/screenings/{run_id}/steps")
def get_screening_steps(
    run_id: str, request: Request, _: User = Depends(require_viewer)
) -> dict[str, Any]:
    """The full trace: every step with what went in and what came out, plus the audit log."""
    store = request.app.state.store
    if store.get(run_id) is None:
        raise HTTPException(status_code=404, detail=f"no screening with id {run_id}")
    return {"run_id": run_id, "steps": store.steps(run_id), "audit": store.audit(run_id)}


# -- actions ----------------------------------------------------------------------------


@router.post("/roles/{role_id}/screenings", status_code=201)
def start_screening(
    role_id: str,
    body: StartScreeningRequest,
    request: Request,
    user: User = Depends(require_recruiter),
) -> dict[str, Any]:
    app = request.app
    role = app.state.data.role(role_id)
    if role is None:
        raise HTTPException(status_code=404, detail=f"no role with id {role_id}")
    candidate = app.state.data.candidate(body.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail=f"no candidate with id {body.candidate_id}")
    if candidate.id not in role.shortlist:
        raise HTTPException(
            status_code=400, detail=f"{candidate.full_name} is not on this role's shortlist"
        )
    problems = problems_for_candidate(app.state.copilot.problems, candidate.id)
    if has_errors(problems):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "this candidate's data failed checks and cannot be screened",
                "problems": [p.message for p in problems if p.severity == "error"],
            },
        )

    run_id = f"run_{uuid4().hex[:12]}"
    store = app.state.store
    store.create(run_id, role.id, candidate.id, started_by=user.name)
    store.add_audit(
        run_id, user.name, "started", f"screening {candidate.full_name} for {role.title}"
    )
    log_event(
        log,
        "screening_started",
        run_id=run_id,
        role_id=role.id,
        candidate_id=candidate.id,
        by=user.name,
    )

    state = _run_copilot(
        request, run_id, lambda: app.state.copilot.start(run_id, role.id, candidate.id)
    )
    store.save_state(run_id, state)
    store.add_audit(run_id, "copilot", state["status"], state.get("error") or "")
    return _screening_response(request, run_id)


@router.post("/screenings/{run_id}/decision")
def decide(
    run_id: str,
    body: DecisionRequest,
    request: Request,
    user: User = Depends(require_recruiter),
) -> dict[str, Any]:
    app = request.app
    store = app.state.store
    screening = store.get(run_id)
    if screening is None:
        raise HTTPException(status_code=404, detail=f"no screening with id {run_id}")
    if screening["status"] != "awaiting_approval" or not app.state.copilot.is_waiting(run_id):
        raise HTTPException(
            status_code=409,
            detail=f"this screening is not waiting for approval (status: {screening['status']})",
        )

    # No message means "send the draft as it is". A message that is there but blank means
    # the recruiter cleared the box; that is refused, never quietly swapped for the draft.
    edited = body.message.strip() if body.message is not None else None
    if body.action == "approve" and edited is not None:
        role = app.state.data.role(screening["role_id"])
        failed = rules.failed(rules.check_message(edited, role))
        if failed:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "the edited message is empty"
                    if not edited
                    else "the edited message breaks a rule",
                    "rules": [r.model_dump() for r in failed],
                },
            )

    detail = "edited the draft" if edited and edited != screening["draft_message"] else ""
    store.add_audit(run_id, user.name, f"{body.action}d", detail)
    state = _run_copilot(
        request,
        run_id,
        lambda: app.state.copilot.decide(run_id, body.action, decided_by=user.name, message=edited),
    )
    store.save_state(run_id, state)
    if state["status"] == "sent":
        store.add_audit(
            run_id, "copilot", "sent", f"message id {state['send_receipt']['message_id']}"
        )
    elif state["status"] != "rejected":
        store.add_audit(run_id, "copilot", state["status"], state.get("error") or "")
    log_event(
        log,
        "screening_decided",
        run_id=run_id,
        action=body.action,
        by=user.name,
        status=state["status"],
    )
    return _screening_response(request, run_id)


# -- helpers ------------------------------------------------------------------------------


def _run_copilot(request: Request, run_id: str, run: Callable[[], dict]) -> dict[str, Any]:
    """Run the copilot. The copilot handles the failures we expect itself; this catches
    anything else so a screening is marked failed with the reason instead of being left
    stuck at "screening" behind a server error."""
    try:
        return run()
    except Exception as err:  # noqa: BLE001 - whatever went wrong, record it on the screening
        log_event(log, "copilot_crashed", logging.ERROR, run_id=run_id, error=repr(err))
        try:
            state = dict(request.app.state.copilot.state(run_id))
        except Exception:  # noqa: BLE001 - the saved state may be unreadable too
            state = {}
        return {**state, "status": "failed", "error": f"unexpected error: {err}"}


def _screening_response(request: Request, run_id: str) -> dict[str, Any]:
    app = request.app
    screening = app.state.store.get(run_id)
    if screening is None:
        raise HTTPException(status_code=404, detail=f"no screening with id {run_id}")
    candidate = app.state.data.candidate(screening["candidate_id"])
    role = app.state.data.role(screening["role_id"])
    screening["candidate_name"] = candidate.full_name if candidate else screening["candidate_id"]
    screening["role_title"] = role.title if role else screening["role_id"]
    screening["requirements"] = (
        [{"id": r.id, "text": r.text, "must_have": r.must_have} for r in role.requirements]
        if role
        else []
    )
    screening["steps"] = [
        {k: v for k, v in step.items() if k != "details"} for step in app.state.store.steps(run_id)
    ]
    return screening
