"""Pick the chat model from settings. "fake" needs no API key and is fully deterministic."""

from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from sourcing_copilot.config import Settings
from sourcing_copilot.data.models import SampleData

from .fake_model import FakeChatModel


class ModelSetupError(Exception):
    pass


def make_model(settings: Settings, data: SampleData) -> BaseChatModel:
    if settings.model == "fake":
        return FakeChatModel(data=data)
    if settings.model == "gemini":
        if not settings.google_api_key:
            raise ModelSetupError("MODEL=gemini needs GOOGLE_API_KEY to be set")
        return init_chat_model(
            f"google_genai:{settings.gemini_model}",
            temperature=0,
            google_api_key=settings.google_api_key,
        )
    raise ModelSetupError(f"unknown MODEL {settings.model!r}; use 'fake' or 'gemini'")
