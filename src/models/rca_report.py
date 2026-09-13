"""Structured RCA report schema."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TimelineEvent(BaseModel):
    timestamp: str = Field(description="Best-available timestamp or relative time (e.g. 'T+2m').")
    event: str
    source: str = Field(description="Where this came from, e.g. 'kubernetes_event', 'metric', 'log', 'trace'.")


class AlternativeExplanation(BaseModel):
    description: str
    why_not_favored: str


class RCAReport(BaseModel):
    observed_facts: list[str] = Field(description="Raw, objective facts observed -- not interpretations.")
    hypotheses_considered: list[str] = Field(description="Every hypothesis investigated, including rejected ones.")
    evidence: list[str] = Field(description="Specific findings that supported or contradicted hypotheses.")

    root_cause: str
    root_cause_service: str
    root_cause_type: str
    affected_services: list[str]
    timeline: list[TimelineEvent]

    confidence: float = Field(ge=0.0, le=1.0)
    confidence_justification: str
    alternative_explanations: list[AlternativeExplanation]
    uncertainty: str = Field(description="What remains unknown or ambiguous.")

    recommended_actions: list[str]
    investigation_summary: str = Field(description="Short narrative of how the investigation proceeded.")
