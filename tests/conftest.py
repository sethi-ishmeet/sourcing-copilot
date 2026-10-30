from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sourcing_copilot.data.load import load_sample_data
from sourcing_copilot.data.models import SampleData

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DATA_DIR = REPO_ROOT / "sample_data"

# Fixed "today" so years of experience and staleness never drift as real time passes.
TODAY = date(2026, 10, 30)


@pytest.fixture(scope="session")
def sample_data() -> SampleData:
    return load_sample_data(SAMPLE_DATA_DIR)


@pytest.fixture
def today() -> date:
    return TODAY
