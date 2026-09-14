from __future__ import annotations

from pydantic import BaseModel, Field


class ProposedChangeItem(BaseModel):
    file: str
    operation: str  # create | modify | delete
    reason: str
    patch: str  # unified diff
    confidence: float = 0.6
    risks: list[str] = Field(default_factory=list)
    acceptance_criterion: str = ""


class ChangeSetOutput(BaseModel):
    changes: list[ProposedChangeItem]
