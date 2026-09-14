"""LLM provider selection with automatic fallback."""
import os
from typing import Any, Type, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from src.llm.gemini import get_gemini_model
from src.llm.groq import get_groq_model

T = TypeVar("T", bound=BaseModel)


def _require_provider() -> tuple[bool, bool]:
    have_gemini = bool(os.environ.get("GEMINI_API_KEY"))
    have_groq = bool(os.environ.get("GROQ_API_KEY"))
    if not have_gemini and not have_groq:
        raise RuntimeError(
            "No LLM provider configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in .env "
            "(see .env.example for where to get free-tier keys)."
        )
    return have_gemini, have_groq


def get_llm(*, tools: list[Any], temperature: float = 0.1) -> BaseChatModel:
    have_gemini, have_groq = _require_provider()
    if have_gemini:
        primary = get_gemini_model(temperature=temperature).bind_tools(tools)
        if have_groq:
            fallback = get_groq_model(temperature=temperature).bind_tools(tools)
            return primary.with_fallbacks([fallback])
        return primary
    return get_groq_model(temperature=temperature).bind_tools(tools)


def get_structured_llm(schema: Type[T], *, temperature: float = 0.1) -> Runnable:
    """LLM configured for structured output (no tools)."""
    have_gemini, have_groq = _require_provider()
    if have_gemini:
        primary = get_gemini_model(temperature=temperature).with_structured_output(schema)
        if have_groq:
            fallback = get_groq_model(temperature=temperature).with_structured_output(schema)
            return primary.with_fallbacks([fallback])
        return primary
    return get_groq_model(temperature=temperature).with_structured_output(schema)
