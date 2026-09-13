"""Hypothesis tracking schema used as a pseudo-tool during investigation."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class HypothesisEntry(BaseModel):
    id: str = Field(description="Short stable id ('h1', 'h2', ...). Reuse the SAME id when "
                                 "updating a hypothesis you already raised -- don't create a new one.")
    description: str = Field(description="Plain-language statement of this hypothesis.")
    target_service: Optional[str] = Field(default=None, description="The service this hypothesis says is at fault.")
    failure_mode: Optional[str] = Field(
        default=None,
        description="One of: application_error, resource_exhaustion, network, dependency_failure, "
                    "configuration, external_system -- or another short label if none fit.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["active", "confirmed", "rejected"] = "active"
    supporting_evidence: str = Field(default="", description="Brief note on what evidence supports this.")
    contradicting_evidence: str = Field(default="", description="Brief note on what evidence contradicts this, if any.")


class InvestigationUpdate(BaseModel):
    """Call this EVERY turn, in addition to any investigation tools you're
    calling, to record your current thinking. This list REPLACES the
    previous one -- include every hypothesis you're still tracking, not
    just ones that changed, and drop ones you've fully ruled out."""

    hypotheses: list[HypothesisEntry]
    overall_confidence: float = Field(
        ge=0.0, le=1.0, description="Your confidence that the current top hypothesis is the true root cause."
    )
    ready_to_conclude: bool = Field(
        description="True only if you have enough evidence to write a confident, well-supported RCA report right "
                    "now. False if you still need to investigate further."
    )
    reasoning: str = Field(description="1-3 sentences: your current thinking, and why you are/aren't ready to conclude.")
