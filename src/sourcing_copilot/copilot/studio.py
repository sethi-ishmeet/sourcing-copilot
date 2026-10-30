"""Open the copilot in LangGraph Studio to watch a run step by step.

    uv run langgraph dev

Then, in Studio, start a run with this input:

    {"run_id": "studio_1", "role_id": "role_backend_sr", "candidate_id": "cand_001"}

The run pauses at wait_for_approval. Resume it from Studio with a decision such as
{"action": "approve", "decided_by": "studio", "decided_at": "now"} or action "reject".

The dev server keeps its own checkpoints (under .langgraph_api/), so this graph is
compiled without the app's SQLite checkpointer. It uses whatever MODEL the .env says.
"""

from __future__ import annotations

from sourcing_copilot.config import load_settings
from sourcing_copilot.copilot.graph import Copilot
from sourcing_copilot.copilot.linkedin import PretendLinkedIn
from sourcing_copilot.copilot.model import make_model
from sourcing_copilot.data.load import load_sample_data


def make_graph():
    settings = load_settings()
    data = load_sample_data(settings.sample_data_dir)
    copilot = Copilot(
        data=data,
        model=make_model(settings, data),
        linkedin=PretendLinkedIn(),
        settings=settings,
    )
    return copilot.build_graph(checkpointer=None)
