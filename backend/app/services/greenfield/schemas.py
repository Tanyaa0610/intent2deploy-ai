"""Structured outputs for greenfield (from-scratch) project generation."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ComponentSpec(BaseModel):
    name: str
    responsibility: str
    files: list[str] = Field(default_factory=list)


class FileSpec(BaseModel):
    path: str
    purpose: str


class ProjectDesign(BaseModel):
    """Requirements analysis + architecture design for a new project."""

    project_name: str
    summary: str
    requirements: list[str]
    non_functional: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str]
    stack: str
    components: list[ComponentSpec]
    files: list[FileSpec]
    dependencies: list[str] = Field(default_factory=list)
    test_command: str = "python3 -m pytest -q"
    run_command: str = ""
    risks: list[str] = Field(default_factory=list)
    # Set only by mock mode: which built-in template produced this design.
    template: str = ""
    # Where the project runs: its host port (its staging-preview port when
    # the repository is on GitHub), used in README and docker-compose.
    port: int = 8010
    preview: bool = False

    @field_validator("requirements", "acceptance_criteria", "components", "files")
    @classmethod
    def _non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("must contain at least one entry")
        return v


class GeneratedFile(BaseModel):
    path: str
    content: str


class GeneratedProject(BaseModel):
    files: list[GeneratedFile]

    @field_validator("files")
    @classmethod
    def _non_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("must contain at least one file")
        return v
