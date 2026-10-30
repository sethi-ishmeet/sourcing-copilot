from __future__ import annotations

import pytest

from sourcing_copilot.config import Settings
from sourcing_copilot.copilot.fake_model import FakeChatModel
from sourcing_copilot.copilot.graph import Copilot
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from tests.conftest import TODAY


@pytest.fixture
def make_copilot(sample_data):
    """Build a copilot with the fake model. Tests pass a behaviour or a LinkedIn double."""

    def _make(
        behaviour: str = "normal",
        linkedin: PretendLinkedIn | None = None,
        settings: Settings | None = None,
        checkpointer=None,
    ) -> Copilot:
        return Copilot(
            data=sample_data,
            model=FakeChatModel(data=sample_data, behaviour=behaviour),
            linkedin=linkedin or PretendLinkedIn(),
            settings=settings or Settings(),
            checkpointer=checkpointer,
            today=lambda: TODAY,
            send_retry_wait_seconds=0,
        )

    return _make
