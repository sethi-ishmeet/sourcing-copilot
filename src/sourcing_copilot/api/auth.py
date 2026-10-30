"""API keys with two roles. A viewer can read everything. A recruiter can also start a
screening and approve or reject a message. Keys come from settings; the defaults are for
local development only."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

ROLE_RANK = {"viewer": 1, "recruiter": 2}


@dataclass(frozen=True)
class User:
    name: str
    role: str  # "viewer" or "recruiter"


def current_user(request: Request, api_key: str | None = Depends(api_key_header)) -> User:
    if not api_key:
        raise HTTPException(status_code=401, detail="missing X-API-Key header")
    settings = request.app.state.settings
    if api_key == settings.recruiter_api_key:
        return User(name="recruiter", role="recruiter")
    if api_key == settings.viewer_api_key:
        return User(name="viewer", role="viewer")
    raise HTTPException(status_code=401, detail="unknown API key")


def require_viewer(user: User = Depends(current_user)) -> User:
    return user


def require_recruiter(user: User = Depends(current_user)) -> User:
    if ROLE_RANK[user.role] < ROLE_RANK["recruiter"]:
        raise HTTPException(
            status_code=403, detail="only a recruiter can do this; your key is a viewer key"
        )
    return user
