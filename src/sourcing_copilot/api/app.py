"""Build the FastAPI app. `create_app()` with no arguments reads settings from the
environment; tests pass their own settings, data and doubles."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite import SqliteSaver

from sourcing_copilot.config import REPO_ROOT, Settings, load_settings
from sourcing_copilot.copilot.graph import Copilot
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from sourcing_copilot.copilot.model import make_model
from sourcing_copilot.data.load import load_sample_data
from sourcing_copilot.data.models import SampleData
from sourcing_copilot.logs import log_event, setup_logging
from sourcing_copilot.store.db import connect
from sourcing_copilot.store.screenings import ScreeningStore

from .routes import router

log = logging.getLogger("api")
FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"


def create_app(
    settings: Settings | None = None,
    data: SampleData | None = None,
    model: BaseChatModel | None = None,
    linkedin: PretendLinkedIn | None = None,
    today: Callable[[], date] | None = None,
    frontend_dist: Path | None = FRONTEND_DIST,
) -> FastAPI:
    settings = settings or load_settings()
    setup_logging(settings.log_level)
    data = data or load_sample_data(settings.sample_data_dir)
    model = model or make_model(settings, data)
    linkedin = linkedin or PretendLinkedIn(
        fail_times=1 if settings.pretend_linkedin_fail_first_send else 0
    )
    today = today or (lambda: datetime.now(UTC).date())

    conn = connect(settings.db_path)
    store = ScreeningStore(conn)
    # The approval pause is checkpointed in the same SQLite file, in LangGraph's own tables.
    checkpointer = SqliteSaver(sqlite3.connect(str(settings.db_path), check_same_thread=False))
    copilot = Copilot(
        data=data,
        model=model,
        linkedin=linkedin,
        settings=settings,
        checkpointer=checkpointer,
        today=today,
    )
    for problem in copilot.problems:
        log_event(
            log,
            "data_check",
            logging.WARNING if problem.severity == "warning" else logging.ERROR,
            check=problem.check,
            source=problem.source,
            record_id=problem.record_id,
            message=problem.message,
        )

    app = FastAPI(title="Sourcing Copilot", version="0.1.0")
    app.state.settings = settings
    app.state.data = data
    app.state.store = store
    app.state.copilot = copilot
    app.state.linkedin = linkedin
    app.state.today = today
    app.include_router(router)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        log_event(
            log,
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            ms=int((time.perf_counter() - started) * 1000),
        )
        return response

    if frontend_dist and (frontend_dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def serve_ui(path: str):
            # Any non-API path is a page in the single-page UI.
            return FileResponse(frontend_dist / "index.html")

    return app
