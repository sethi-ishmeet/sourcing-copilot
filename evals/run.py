"""Run the eval cases and write a report.

    uv run python -m evals.run --model fake --trials 1 --out reports/evals
    uv run python -m evals.run --model gemini --trials 3 --judge --out reports/evals

A case passes a trial when every criterion it lists passes. With several trials, a case
passes when more than half of its trials pass. The suite passes when the share of passing
cases meets the threshold. Cases marked "fake_only" need the fake model's misbehaviour
switches and are skipped for a real model.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

from sourcing_copilot.config import REPO_ROOT, Settings, load_settings
from sourcing_copilot.copilot.fake_model import FakeChatModel
from sourcing_copilot.copilot.graph import Copilot
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from sourcing_copilot.copilot.model import make_model
from sourcing_copilot.data.load import load_sample_data
from sourcing_copilot.data.models import SampleData
from sourcing_copilot.logs import setup_logging

from .judge import judge_message
from .scorers import CRITERIA, RunOutcome, score_case

CASES_PATH = REPO_ROOT / "evals" / "cases.jsonl"
DEFAULT_THRESHOLD = 0.85


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_one(
    case: dict, data: SampleData, model_name: str, settings: Settings, today: date
) -> RunOutcome:
    linkedin = PretendLinkedIn(**case.get("linkedin", {}))
    if model_name == "fake":
        model = FakeChatModel(data=data, behaviour=case.get("fake_behaviour", "normal"))
    else:
        model = make_model(settings, data)
    copilot = Copilot(
        data=data,
        model=model,
        linkedin=linkedin,
        settings=settings,
        today=lambda: today,
        send_retry_wait_seconds=0,
    )
    run_id = f"eval_{uuid4().hex[:8]}"
    started = time.perf_counter()
    attempts_before_decision = 0
    try:
        state = copilot.start(run_id, case["role_id"], case["candidate_id"])
        attempts_before_decision = len(linkedin.attempts)
        if case.get("decision") and state["status"] == "awaiting_approval":
            state = copilot.decide(run_id, case["decision"], decided_by="eval")
    except Exception:  # noqa: BLE001 - a crash is a result to report, not a reason to stop
        ms = int((time.perf_counter() - started) * 1000)
        state = {
            "status": "crashed",
            "steps": [],
            "candidate_id": case["candidate_id"],
            "role_id": case["role_id"],
        }
        return RunOutcome(
            state, linkedin, attempts_before_decision, ms, crashed=traceback.format_exc()
        )
    return RunOutcome(
        state, linkedin, attempts_before_decision, int((time.perf_counter() - started) * 1000)
    )


def run_evals(
    model_name: str,
    trials: int = 1,
    out_dir: Path | None = None,
    cases_path: Path = CASES_PATH,
    threshold: float = DEFAULT_THRESHOLD,
    judge: bool = False,
    today: date | None = None,
    settings: Settings | None = None,
) -> dict:
    settings = settings or load_settings()
    settings = Settings(**{**settings.__dict__, "model": model_name})
    data = load_sample_data(settings.sample_data_dir)
    today = today or datetime.now(UTC).date()
    judge_model = make_model(settings, data) if judge and model_name != "fake" else None
    model_label = "fake" if model_name == "fake" else settings.gemini_model

    cases_out: list[dict] = []
    skipped: list[dict] = []
    criteria_totals = {c: {"passed": 0, "checked": 0} for c in CRITERIA}

    for case in load_cases(cases_path):
        if case.get("model") == "fake_only" and model_name != "fake":
            skipped.append({"id": case["id"], "why": "needs the fake model's misbehaviour switch"})
            continue
        trial_rows = []
        for trial in range(1, trials + 1):
            outcome = run_one(case, data, model_name, settings, today)
            results = score_case(case, outcome, data)
            for name, result in results.items():
                criteria_totals[name]["checked"] += 1
                criteria_totals[name]["passed"] += int(result.passed)
            row = {
                "trial": trial,
                "passed": all(r.passed for r in results.values()),
                "status": outcome.state.get("status"),
                "error": outcome.state.get("error"),
                "ms": outcome.ms,
                "tokens_in": sum(s.get("tokens_in", 0) for s in outcome.state.get("steps", [])),
                "tokens_out": sum(s.get("tokens_out", 0) for s in outcome.state.get("steps", [])),
                "criteria": {n: {"passed": r.passed, "notes": r.notes} for n, r in results.items()},
                "draft_message": outcome.state.get("draft_message"),
                "scorecard": outcome.state.get("scorecard"),
            }
            if judge_model is not None and outcome.state.get("draft_message"):
                role = data.role(case["role_id"])
                row["message_quality"] = judge_message(
                    judge_model, role, outcome.state["scorecard"], outcome.state["draft_message"]
                )
            trial_rows.append(row)
            print(
                f"{case['id']:<58} trial {trial}: {'pass' if row['passed'] else 'FAIL'}  "
                f"({row['status']}, {row['ms']} ms)",
                flush=True,
            )
        passes = sum(r["passed"] for r in trial_rows)
        cases_out.append(
            {
                "id": case["id"],
                "about": case["about"],
                "criteria": case["criteria"],
                "injected_failure": case.get("injected_failure"),
                "trials_passed": passes,
                "trials": trial_rows,
                "passed": passes * 2 > len(trial_rows),
            }
        )

    cases_passed = sum(c["passed"] for c in cases_out)
    pass_rate = cases_passed / len(cases_out) if cases_out else 0.0
    report = {
        "model": model_label,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "trials_per_case": trials,
        "threshold": threshold,
        "judge": judge_model is not None,
        "summary": {
            "cases_total": len(cases_out) + len(skipped),
            "cases_run": len(cases_out),
            "cases_passed": cases_passed,
            "pass_rate": round(pass_rate, 3),
            "passed": pass_rate >= threshold,
            "criteria": criteria_totals,
            "total_ms": sum(t["ms"] for c in cases_out for t in c["trials"]),
            "total_tokens": sum(
                t["tokens_in"] + t["tokens_out"] for c in cases_out for t in c["trials"]
            ),
        },
        "cases": cases_out,
        "skipped": skipped,
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = "fake-model" if model_name == "fake" else model_label
        (out_dir / f"{stem}.json").write_text(json.dumps(report, indent=2))
        (out_dir / f"{stem}.md").write_text(to_markdown(report))
        print(f"\nwrote {out_dir / (stem + '.json')} and {out_dir / (stem + '.md')}")
    return report


def to_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# Eval report: {report['model']}",
        "",
        f"Run at {report['run_at']} with today pinned to {report['today']}. "
        f"{report['trials_per_case']} trial(s) per case; a case passes when more than half of "
        f"its trials pass. Suite threshold: {int(report['threshold'] * 100)}% of cases.",
        "",
        "## Summary",
        "",
        f"- Result: **{'PASS' if s['passed'] else 'FAIL'}** "
        f"({s['cases_passed']} of {s['cases_run']} cases passed, {int(s['pass_rate'] * 100)}%)",
        f"- Skipped: {len(report['skipped'])}",
        f"- Total time: {s['total_ms']} ms; total tokens: {s['total_tokens']}",
        "",
        "| Criterion | Passed | Checked |",
        "|---|---|---|",
    ]
    for name, totals in s["criteria"].items():
        lines.append(f"| {name} | {totals['passed']} | {totals['checked']} |")
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Injected failure | Trials passed | Result | Last status | Avg ms | Tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report["cases"]:
        avg_ms = int(sum(t["ms"] for t in c["trials"]) / len(c["trials"]))
        tokens = sum(t["tokens_in"] + t["tokens_out"] for t in c["trials"])
        lines.append(
            f"| {c['id']} | {c['injected_failure'] or ''} | "
            f"{c['trials_passed']}/{len(c['trials'])} | {'pass' if c['passed'] else 'FAIL'} | "
            f"{c['trials'][-1]['status']} | {avg_ms} | {tokens} |"
        )
    if report["judge"]:
        lines += [
            "",
            "## Message quality (model-judged, not gating)",
            "",
            "| Case | Trial | Score | Reasons |",
            "|---|---|---|---|",
        ]
        for c in report["cases"]:
            for t in c["trials"]:
                q = t.get("message_quality")
                if q:
                    lines.append(f"| {c['id']} | {t['trial']} | {q['score']} | {q['reasons']} |")
    notes = [
        (c["id"], t["trial"], name, r["notes"])
        for c in report["cases"]
        for t in c["trials"]
        for name, r in t["criteria"].items()
        if not r["passed"]
    ]
    lines += ["", "## Failed checks", ""]
    if not notes:
        lines.append("None.")
    for case_id, trial, name, why in notes:
        lines.append(f"- {case_id}, trial {trial}, {name}: {'; '.join(why)}")
    if report["skipped"]:
        lines += ["", "## Skipped", ""] + [f"- {sk['id']}: {sk['why']}" for sk in report["skipped"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the copilot evals.")
    parser.add_argument("--model", choices=["fake", "gemini"], default="fake")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "reports" / "evals")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--judge", action="store_true", help="also score message quality with the model"
    )
    parser.add_argument("--today", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    setup_logging("WARNING")
    report = run_evals(
        args.model, args.trials, args.out, args.cases, args.threshold, args.judge, args.today
    )
    s = report["summary"]
    print(
        f"\n{'PASS' if s['passed'] else 'FAIL'}: {s['cases_passed']}/{s['cases_run']} cases "
        f"({int(s['pass_rate'] * 100)}%), threshold {int(args.threshold * 100)}%"
    )
    return 0 if s["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
