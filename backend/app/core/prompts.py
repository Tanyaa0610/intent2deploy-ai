"""Prompt template loader.

Prompt templates live in `backend/prompts/*.md` as YAML frontmatter +
Markdown body (master spec §11). The frontmatter records purpose, input
schema, output schema, safety constraints, and a version string. The
version is logged against every workflow event that uses a prompt, giving
the auditable "prompt version used for every workflow" required by the
spec.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class PromptTemplate:
    name: str
    version: str
    purpose: str
    input_schema: str
    output_schema: str
    safety_constraints: list[str]
    system_instruction: str

    def render(self, **kwargs: object) -> str:
        try:
            return self.system_instruction.format(**kwargs)
        except KeyError as exc:
            raise ValueError(f"Missing prompt variable {exc} for template '{self.name}'") from exc


@lru_cache(maxsize=None)
def load_prompt(name: str) -> PromptTemplate:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"Prompt template '{name}' is missing YAML frontmatter")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)

    system_match = re.search(r"## System Instruction\s*\n(.*?)(\n## |\Z)", body, re.DOTALL)
    system_instruction = system_match.group(1).strip() if system_match else body.strip()

    return PromptTemplate(
        name=name,
        version=str(meta.get("version", "v1")),
        purpose=str(meta.get("purpose", "")),
        input_schema=str(meta.get("input_schema", "")),
        output_schema=str(meta.get("output_schema", "")),
        safety_constraints=list(meta.get("safety_constraints", [])),
        system_instruction=system_instruction,
    )


def all_prompt_names() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))
