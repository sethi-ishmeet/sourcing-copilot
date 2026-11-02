"""The one browser test, covering the critical path a recruiter takes: open the role,
screen a candidate, read the scorecard and the draft, approve, see it sent.

It starts a real server (fake model, fresh database) and drives the built UI with
Playwright. Screenshots go to reports/browser/ so a failure is easy to understand.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from sourcing_copilot.config import load_settings
from sourcing_copilot.data.load import load_sample_data
from sourcing_copilot.data.profile import years_of_experience

pytestmark = pytest.mark.browser

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST = REPO_ROOT / "frontend" / "dist"
SCREENSHOTS = REPO_ROOT / "reports" / "browser"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if not (DIST / "index.html").exists():
        pytest.fail("frontend/dist is missing; run `make ui-build` before the browser test")
    port = _free_port()
    env = {
        **os.environ,
        "MODEL": "fake",
        "DB_PATH": str(tmp_path_factory.mktemp("db") / "browser.sqlite"),
        "LOG_LEVEL": "WARNING",
    }
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    server_log = (SCREENSHOTS / "server.log").open("w")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "sourcing_copilot.api.app:create_app",
            "--factory",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=server_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.25)
    else:
        proc.terminate()
        pytest.fail(f"server did not start; see {SCREENSHOTS / 'server.log'}")
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    server_log.close()


def _priya_years_today() -> str:
    """The server counts years of experience up to today's real date, so the test works
    out the expected number the same way instead of hard-coding one that goes stale."""
    data = load_sample_data(load_settings().sample_data_dir)
    years = years_of_experience(data.candidate("cand_001"), datetime.now(UTC).date())
    return f"{years:g}"  # the page shows 8.0 as "8", like JavaScript does


def test_screen_a_candidate_and_approve_the_message(page: Page, server: str):
    # The role page lists the shortlist with computed facts.
    page.goto(server)
    expect(page.get_by_role("heading", level=1)).to_contain_text("Senior Backend Engineer")
    row = page.get_by_test_id("candidate-cand_001")
    expect(row).to_contain_text("Priya Raman")
    expect(row).to_contain_text(_priya_years_today())
    expect(row).to_contain_text("not screened")

    # Screen her: the page moves to the screening with a scorecard and a draft.
    page.get_by_test_id("screen-cand_001").click()
    page.wait_for_url("**/screenings/**")
    # The screening runs inside the request; give a slow CI machine time.
    expect(page.get_by_test_id("status")).to_have_text("Waiting for approval", timeout=15000)
    expect(page.get_by_test_id("score-row")).to_have_count(4)
    expect(page.get_by_test_id("scorecard")).to_contain_text("Recommended")
    draft = page.get_by_test_id("draft")
    expect(draft).not_to_be_empty()
    assert "Acme Health" in draft.input_value()
    page.screenshot(path=SCREENSHOTS / "1-waiting-for-approval.png", full_page=True)

    # Approve: the message goes out and the page shows what happened.
    page.get_by_test_id("approve").click()
    try:
        expect(page.get_by_test_id("status")).to_have_text("Sent", timeout=15000)
    except AssertionError:
        # Make a failure here easy to read in CI: what the page said, and what the server saw.
        print("PAGE TEXT AFTER APPROVE:\n" + page.locator("main").inner_text())
        print("SERVER LOG:\n" + (SCREENSHOTS / "server.log").read_text())
        raise
    expect(page.get_by_test_id("final-message")).to_contain_text("Acme Health")
    expect(page.get_by_test_id("steps")).to_contain_text("send")
    expect(page.get_by_test_id("audit")).to_contain_text("approved")
    expect(page.get_by_test_id("audit")).to_contain_text("sent")
    page.screenshot(path=SCREENSHOTS / "2-sent.png", full_page=True)

    # Back on the role page, the shortlist shows the result.
    page.goto(server)
    expect(page.get_by_test_id("candidate-cand_001")).to_contain_text("Sent")
    page.screenshot(path=SCREENSHOTS / "3-shortlist-after.png", full_page=True)
