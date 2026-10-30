"""The eval suite is also a test: with the fake model every case must pass, every time.
This is the pull-request gate. The nightly run against the real model allows variance."""

from __future__ import annotations

from evals.run import load_cases, run_evals
from tests.conftest import TODAY


def test_every_case_passes_with_the_fake_model(tmp_path):
    report = run_evals("fake", trials=1, out_dir=tmp_path, today=TODAY)
    failures = [
        (c["id"], name, r["notes"])
        for c in report["cases"]
        for t in c["trials"]
        for name, r in t["criteria"].items()
        if not r["passed"]
    ]
    assert failures == []
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["cases_run"] == len(load_cases())
    assert (tmp_path / "fake-model.md").exists()


def test_every_case_lists_only_known_criteria():
    from evals.scorers import CRITERIA

    for case in load_cases():
        assert set(case["criteria"]) <= set(CRITERIA), case["id"]
        assert case["criteria"], case["id"]
