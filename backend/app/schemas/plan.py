from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class PlanStep(BaseModel):
    id: str
    description: str
    files: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    """Structured plan output. Mirrors master spec §10 exactly."""

    summary: str
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    steps: list[PlanStep]
    files_likely_to_change: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    test_strategy: list[str]
    risks: list[str] = Field(default_factory=list)

    @field_validator("acceptance_criteria", "steps", "test_strategy")
    @classmethod
    def _non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("must contain at least one entry")
        return v


class RetrievalEvidenceItem(BaseModel):
    file: str
    start_line: int
    end_line: int
    score: float
    reason: str
