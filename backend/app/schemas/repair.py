from __future__ import annotations

from pydantic import BaseModel, Field


class RepairProposal(BaseModel):
    diagnosis: str
    root_cause: str
    repair_patch: str  # unified diff
    confidence: float = 0.5
    files: list[str] = Field(default_factory=list)
