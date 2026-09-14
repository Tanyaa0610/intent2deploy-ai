from __future__ import annotations

from pydantic import BaseModel, Field


class GeneratedTestItem(BaseModel):
    file: str
    content: str
    rationale: str
    category: str = "happy_path"


class TestSetOutput(BaseModel):
    tests: list[GeneratedTestItem] = Field(default_factory=list)
    existing_tests_found: int = 0
    relevant_tests: int = 0
