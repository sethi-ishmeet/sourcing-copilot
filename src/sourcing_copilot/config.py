"""All settings come from environment variables.

A `.env` file in the repo root is loaded if it exists, so local runs do not need to
export anything. Tests build their own Settings instead of reading the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str = "fake"  # "fake" or "gemini"
    gemini_model: str = "gemini-3.8-flash"
    google_api_key: str | None = None
    db_path: Path = REPO_ROOT / "data" / "sourcing_copilot.sqlite"
    sample_data_dir: Path = REPO_ROOT / "sample_data"
    viewer_api_key: str = "viewer-dev-key"
    recruiter_api_key: str = "recruiter-dev-key"
    max_tool_calls: int = 6
    pretend_linkedin_fail_first_send: bool = False
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Build Settings from the environment, falling back to safe local defaults."""
    env = os.environ
    return Settings(
        model=env.get("MODEL", "fake").strip().lower(),
        gemini_model=env.get("GEMINI_MODEL", "gemini-3.8-flash"),
        google_api_key=env.get("GOOGLE_API_KEY") or None,
        db_path=Path(env.get("DB_PATH", str(REPO_ROOT / "data" / "sourcing_copilot.sqlite"))),
        sample_data_dir=Path(env.get("SAMPLE_DATA_DIR", str(REPO_ROOT / "sample_data"))),
        viewer_api_key=env.get("VIEWER_API_KEY", "viewer-dev-key"),
        recruiter_api_key=env.get("RECRUITER_API_KEY", "recruiter-dev-key"),
        max_tool_calls=int(env.get("MAX_TOOL_CALLS", "6")),
        pretend_linkedin_fail_first_send=_as_bool(
            env.get("PRETEND_LINKEDIN_FAIL_FIRST_SEND"), False
        ),
        log_level=env.get("LOG_LEVEL", "INFO").upper(),
    )
