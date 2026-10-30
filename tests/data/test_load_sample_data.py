"""The shipped sample data loads, is clean, and carries exactly the warnings we planted."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sourcing_copilot.data.checks import has_errors, run_data_checks
from sourcing_copilot.data.load import DataLoadError, load_sample_data
from tests.conftest import SAMPLE_DATA_DIR


def test_sample_data_loads_with_expected_counts(sample_data):
    assert len(sample_data.candidates) == 10
    assert [r.id for r in sample_data.roles] == ["role_backend_sr", "role_ml_platform"]
    assert len(sample_data.do_not_contact) == 2


def test_sample_data_has_no_errors_and_only_the_planted_warnings(sample_data, today):
    problems = run_data_checks(sample_data, today)
    assert not has_errors(problems), [p.message for p in problems if p.severity == "error"]
    warnings = {(p.check, p.record_id) for p in problems}
    assert warnings == {
        ("stale_profile", "cand_005"),
        ("suspicious_text", "cand_004"),
        ("do_not_contact_unmatched", "https://www.linkedin.com/in/jamie-fox-sample"),
    }


def test_every_shortlisted_candidate_exists(sample_data):
    ids = {c.id for c in sample_data.candidates}
    for role in sample_data.roles:
        assert set(role.shortlist) <= ids


def _copy_sample_data(tmp_path: Path) -> Path:
    target = tmp_path / "sample_data"
    shutil.copytree(SAMPLE_DATA_DIR, target)
    return target


def test_broken_json_fails_loudly(tmp_path):
    folder = _copy_sample_data(tmp_path)
    (folder / "candidates.json").write_text('[{"id": ')
    with pytest.raises(DataLoadError, match="candidates.json: not valid JSON"):
        load_sample_data(folder)


def test_missing_field_fails_with_the_field_name(tmp_path):
    folder = _copy_sample_data(tmp_path)
    records = json.loads((folder / "candidates.json").read_text())
    del records[0]["headline"]
    (folder / "candidates.json").write_text(json.dumps(records))
    with pytest.raises(DataLoadError, match=r"candidates.json: 0.headline"):
        load_sample_data(folder)


def test_bad_month_format_is_rejected(tmp_path):
    folder = _copy_sample_data(tmp_path)
    records = json.loads((folder / "candidates.json").read_text())
    records[0]["experience"][0]["start_date"] = "March 2021"
    (folder / "candidates.json").write_text(json.dumps(records))
    with pytest.raises(DataLoadError, match="expected YYYY-MM"):
        load_sample_data(folder)


def test_missing_csv_fails_loudly(tmp_path):
    folder = _copy_sample_data(tmp_path)
    (folder / "do_not_contact.csv").unlink()
    with pytest.raises(DataLoadError, match="do_not_contact.csv: file not found"):
        load_sample_data(folder)
