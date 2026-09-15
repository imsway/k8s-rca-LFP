"""LangGraph shared state schema for the investigation loop."""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import add_messages

from src.models.evidence import Evidence
from src.models.hypothesis import HypothesisEntry
from src.models.rca_report import RCAReport


class InvestigationState(TypedDict):
    messages: Annotated[list, add_messages]

    incident_description: str

    hypotheses: list[HypothesisEntry]
    overall_confidence: float
    ready_to_conclude: bool

    evidence: Annotated[list[Evidence], operator.add]
    tool_call_history: Annotated[list[str], operator.add]

    iteration: int
    max_iterations: int
    tool_calls_used: int
    tool_call_budget: int

    rca_report: Optional[RCAReport]


def initial_state(incident_description: str, max_iterations: int = 8, tool_call_budget: int = 30) -> InvestigationState:
    return InvestigationState(
        messages=[],
        incident_description=incident_description,
        hypotheses=[],
        overall_confidence=0.0,
        ready_to_conclude=False,
        evidence=[],
        tool_call_history=[],
        iteration=0,
        max_iterations=max_iterations,
        tool_calls_used=0,
        tool_call_budget=tool_call_budget,
        rca_report=None,
    )
