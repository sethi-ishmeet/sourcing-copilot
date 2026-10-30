from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sourcing_copilot.api.app import create_app
from sourcing_copilot.config import Settings
from sourcing_copilot.copilot.fake_model import FakeChatModel
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from tests.conftest import TODAY

VIEWER = {"X-API-Key": "viewer-dev-key"}
RECRUITER = {"X-API-Key": "recruiter-dev-key"}


@pytest.fixture
def make_client(sample_data, tmp_path):
    """A test client over a fresh app with its own SQLite file and the fake model."""

    def _make(behaviour: str = "normal", linkedin: PretendLinkedIn | None = None) -> TestClient:
        settings = Settings(db_path=tmp_path / "test.sqlite")
        app = create_app(
            settings=settings,
            data=sample_data,
            model=FakeChatModel(data=sample_data, behaviour=behaviour),
            linkedin=linkedin or PretendLinkedIn(),
            today=lambda: TODAY,
            frontend_dist=None,
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


def start_screening(client: TestClient, candidate_id: str, role_id: str = "role_backend_sr"):
    return client.post(
        f"/api/roles/{role_id}/screenings", json={"candidate_id": candidate_id}, headers=RECRUITER
    )
