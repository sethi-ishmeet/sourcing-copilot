"""The API answers requests from a thread pool, and the UI fires several at once. The
store must give every thread the right answer. Found by the browser test: without a
lock on reads, a screening fetched right after it was created sometimes came back as
"not found"."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sourcing_copilot.store.db import connect
from sourcing_copilot.store.screenings import ScreeningStore


def test_concurrent_reads_and_writes_always_see_the_right_rows():
    store = ScreeningStore(connect(":memory:"))
    store.create("run_1", "role_backend_sr", "cand_001", "recruiter")
    steps = [
        {"name": f"step {i}", "status": "ok", "started_at": "t", "details": {"i": i}}
        for i in range(12)
    ]
    store.save_state("run_1", {"status": "awaiting_approval", "steps": steps})

    problems: list[str] = []

    def read_and_write(worker: int) -> None:
        for n in range(200):
            try:
                if store.get("run_1") is None:
                    problems.append("get returned None")
                if len(store.steps("run_1")) != 12:
                    problems.append("steps had the wrong length")
                if "cand_001" not in store.latest_for_role("role_backend_sr"):
                    problems.append("latest_for_role missed the row")
                if worker == 0 and n % 20 == 0:
                    store.add_audit("run_1", "test", "ping")
                    store.save_state("run_1", {"status": "awaiting_approval", "steps": steps})
            except Exception as err:  # noqa: BLE001 - any error is a failure to report
                problems.append(f"{type(err).__name__}: {err}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(read_and_write, range(8)))

    assert problems == []
