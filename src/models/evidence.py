from __future__ import annotations

import time

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    id: str
    tool_name: str
    tool_args: dict
    result: str
    timestamp: float = Field(default_factory=time.time)
