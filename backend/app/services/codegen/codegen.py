"""Code-change proposal generation (master spec §12).

Never simply asks the LLM to "rewrite the repository." Instead: take the
approved plan, read the actual current content of the files the plan
references, ask for a structured, file-scoped change proposal, and
enforce hard safety limits (max files changed, max patch lines) before
the result is ever shown to the user for approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.schemas.change import ChangeSetOutput
from app.services.codegen.diffing import count_patch_lines
from app.services.providers.base import LLMProvider

MAX_CONTENT_CHARS_PER_FILE = 4000


class ChangeGenerationLimitError(Exception):
    pass


@dataclass
class ChangeGenerationResult:
    changeset: ChangeSetOutput
    prompt_version: str
    raw_llm_output: str
    context_text: str
    llm_estimated_tokens: int  # ESTIMATE: (len(rendered)+len(raw_text))//4


def _read_file_contents(repo_root: Path, files: list[str]) -> dict[str, str]:
    contents: dict[str, str] = {}
    for f in files:
        path = repo_root / f
        if path.is_file():
            try:
                contents[f] = path.read_text(encoding="utf-8", errors="ignore")[:20000]
            except OSError:
                continue
    return contents


def generate_changes(
    provider: LLMProvider,
    repo_root: Path,
    target_files: list[str],
    intent: str,
    plan_summary: str,
    approved_steps: list[str],
) -> ChangeGenerationResult:
    file_contents = _read_file_contents(repo_root, target_files)

    prompt = load_prompt("code_modification")
    context_text = "\n\n".join(
        f"### {f}\n{content[:MAX_CONTENT_CHARS_PER_FILE]}" for f, content in file_contents.items()
    ) or "(no existing file content available)"
    rendered = prompt.render(
        plan_summary=plan_summary,
        approved_steps="; ".join(approved_steps),
        retrieved_context=context_text,
        target_files=target_files,
    )

    result = structured_call(
        provider,
        "code_modification",
        rendered,
        {"intent": intent, "file_contents": file_contents},
        schema=ChangeSetOutput,
    )
    changeset = result.parsed

    # --- Enforce hard safety limits (master spec §34) ------------------
    if len(changeset.changes) > settings.max_files_changed:
        raise ChangeGenerationLimitError(
            f"Proposed change touches {len(changeset.changes)} files, exceeding "
            f"MAX_FILES_CHANGED={settings.max_files_changed}."
        )
    for change in changeset.changes:
        lines = count_patch_lines(change.patch)
        if lines > settings.max_patch_lines:
            raise ChangeGenerationLimitError(
                f"Patch for '{change.file}' has {lines} changed lines, exceeding "
                f"MAX_PATCH_LINES={settings.max_patch_lines}."
            )

    estimated_tokens = (len(rendered) + len(result.raw_text)) // 4
    return ChangeGenerationResult(
        changeset=changeset,
        prompt_version=prompt.version,
        raw_llm_output=result.raw_text,
        context_text=context_text,
        llm_estimated_tokens=estimated_tokens,
    )
