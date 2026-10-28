"""Greenfield pipeline: requirements + architecture design, then full project
generation, for repositories with no usable source code.

The output plugs into the normal workflow: the design becomes the Plan (so
plan approval, risk analysis and the scope guardrail work unchanged) and the
generated files become `create` ProposedChanges (so change approval,
workspace application, validation, repair and commit work unchanged).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.core.config import settings
from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.schemas.change import ChangeSetOutput, ProposedChangeItem
from app.schemas.plan import PlanOutput, PlanStep
from app.services.codegen.codegen import ChangeGenerationLimitError, ChangeGenerationResult
from app.services.codegen.diffing import count_patch_lines, make_new_file_diff, make_unified_diff
from app.services.greenfield.schemas import GeneratedProject, ProjectDesign
from app.services.providers.base import LLMProvider

# Extensions that count as "usable source code". Docs, licences, lockfiles
# and config alone do not: a repository with only a README is greenfield.
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".svelte", ".html", ".htm", ".css", ".scss",
    ".java", ".kt", ".kts", ".scala", ".go", ".rs", ".rb", ".php", ".cs", ".fs", ".swift", ".m", ".dart",
    ".c", ".h", ".cc", ".cpp", ".hpp", ".lua", ".r", ".jl", ".ex", ".exs", ".erl", ".clj", ".sh", ".sql",
}


class GreenfieldError(Exception):
    pass


def is_source_file(path: str) -> bool:
    return PurePosixPath(path.replace("\\", "/")).suffix.lower() in SOURCE_EXTENSIONS


def _safe_path(path: str) -> str | None:
    p = path.strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    parts = PurePosixPath(p).parts
    if not p or p.startswith("/") or ":" in p or ".." in parts or (parts and parts[0] == ".git"):
        return None
    return p


@dataclass
class DesignResult:
    design: ProjectDesign
    prompt_version: str
    raw_llm_output: str
    llm_estimated_tokens: int


def design_project(
    provider: LLMProvider, intent: str, existing_files: list[str], port: int = 8010, preview: bool = False,
    revision: bool = False,
) -> DesignResult:
    prompt = load_prompt("project_design")
    rendered = prompt.render(
        intent=intent, existing_files=existing_files or "(none)", max_files=settings.max_greenfield_files, port=port
    )
    result = structured_call(
        provider,
        "project_design",
        rendered,
        {"intent": intent, "existing_files": existing_files, "port": port, "preview": preview},
        schema=ProjectDesign,
    )
    design = result.parsed
    design.port, design.preview = port, preview  # the address is decided by Intent2Deploy, not the model

    # Never plan over existing files (except in a revision, which updates
    # them); drop unsafe paths.
    existing = {f.replace("\\", "/") for f in existing_files}
    kept = []
    for f in design.files:
        safe = _safe_path(f.path)
        if safe and (revision or safe not in existing):
            f.path = safe
            kept.append(f)
    if not kept:
        raise GreenfieldError("The project design contains no files that can be created.")
    design.files = kept
    allowed = {f.path for f in kept}
    for c in design.components:
        c.files = [p for p in (_safe_path(x) for x in c.files) if p in allowed]

    # Every project ships containerized: make sure the Docker files are part of
    # the approved design (and therefore the approved scope) even if the model
    # left them out; generate_project fills them in if it doesn't write them.
    from app.services.greenfield.schemas import ComponentSpec, FileSpec
    from app.services.greenfield.templates import DOCKER_COMPONENT, DOCKER_FILE_SPECS

    for spec in DOCKER_FILE_SPECS:
        if spec["path"] not in allowed and (revision or spec["path"] not in existing):
            design.files.append(FileSpec(**spec))
    if not any(c.name == "Container" for c in design.components):
        design.components.append(ComponentSpec(**DOCKER_COMPONENT))

    tokens = (len(rendered) + len(result.raw_text)) // 4
    return DesignResult(design=design, prompt_version=prompt.version, raw_llm_output=result.raw_text, llm_estimated_tokens=tokens)


def design_to_plan(design: ProjectDesign) -> PlanOutput:
    steps = [
        PlanStep(id=f"S{i}", description=f"Create {c.name}: {c.responsibility}", files=c.files)
        for i, c in enumerate(design.components, start=1)
    ]
    steps.append(
        PlanStep(id=f"S{len(steps) + 1}", description=f"Run the generated test suite ({design.test_command}).", files=[])
    )
    assumptions = [
        "The repository has no usable source code, so the project is generated from scratch.",
        f"Stack: {design.stack}.",
        *design.non_functional,
    ]
    if design.template:
        assumptions.insert(
            1,
            f"Mock mode: generated from the built-in '{design.template}' template, personalised from the request. "
            "Set LLM_MODE=live for an intent-specific project.",
        )
    return PlanOutput(
        summary=design.summary,
        assumptions=assumptions,
        acceptance_criteria=design.acceptance_criteria,
        steps=steps,
        files_likely_to_change=[f.path for f in design.files],
        dependencies=design.dependencies,
        test_strategy=[
            f"Run the generated suite with `{design.test_command}`.",
            "Lint and security-scan the new code (ruff, ruff --select S).",
        ],
        risks=design.risks,
    )


def generate_project(
    provider: LLMProvider, intent: str, design: ProjectDesign, existing_files: list[str], revise_root: Path | None = None
) -> ChangeGenerationResult:
    """Generate the project's files as changes. Normally only new files are
    created; with `revise_root` (a revision of a generated project) files that
    exist are updated with a diff, and unchanged files are left out."""
    prompt = load_prompt("project_generation")
    design_json = design.model_dump_json(indent=2)
    rendered = prompt.render(intent=intent, design_json=design_json)
    result = structured_call(
        provider,
        "project_generation",
        rendered,
        {"intent": intent, "design": json.loads(design_json)},
        schema=GeneratedProject,
    )

    existing = {f.replace("\\", "/") for f in existing_files}
    purposes = {f.path: f.purpose for f in design.files}
    changes: list[ProposedChangeItem] = []
    contents: dict[str, str] = {}
    for f in result.parsed.files:
        path = _safe_path(f.path)
        if path is None:
            continue  # never write outside the repo
        if path in existing:
            if revise_root is None:
                continue  # never overwrite an existing file outside a revision
            new = f.content if f.content.endswith("\n") else f.content + "\n"
            try:
                old = (revise_root / path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            contents[path] = f.content
            if old.replace("\r\n", "\n") != new:
                changes.append(ProposedChangeItem(
                    file=path, operation="modify", reason=f"Revised: {purposes.get(path, 'updated file')}",
                    patch=make_unified_diff(path, old, new), confidence=0.6 if design.template else 0.7,
                    risks=[], acceptance_criterion="",
                ))
            continue
        contents[path] = f.content
        changes.append(
            ProposedChangeItem(
                file=path,
                operation="create",
                reason=purposes.get(path, "New file generated for the project."),
                patch=make_new_file_diff(path, f.content if f.content.endswith("\n") else f.content + "\n"),
                confidence=0.6 if design.template else 0.7,
                risks=[],
                acceptance_criterion="",
            )
        )

    _ensure_containerized(changes, contents, design, existing)

    # Same hard limits as ordinary code generation (master spec §34).
    if len(changes) > settings.max_greenfield_files:
        raise ChangeGenerationLimitError(
            f"Generated project has {len(changes)} files, exceeding MAX_GREENFIELD_FILES={settings.max_greenfield_files}."
        )
    for c in changes:
        lines = count_patch_lines(c.patch)
        if lines > settings.max_patch_lines:
            raise ChangeGenerationLimitError(
                f"Generated file {c.file} has {lines} lines, exceeding MAX_PATCH_LINES={settings.max_patch_lines}."
            )

    return ChangeGenerationResult(
        changeset=ChangeSetOutput(changes=changes),
        prompt_version=prompt.version,
        raw_llm_output=result.raw_text,
        context_text=design_json,
        llm_estimated_tokens=(len(rendered) + len(result.raw_text)) // 4,
    )


def _ensure_containerized(
    changes: list[ProposedChangeItem], contents: dict[str, str], design: ProjectDesign, existing: set[str]
) -> None:
    """If the generated project has no Dockerfile, add the standard Docker
    setup for the detected project type (README gets a Docker section)."""
    from app.services import containerize

    if containerize.has_dockerfile(contents):
        return
    spec = containerize.detect(contents)
    if spec is None:
        return  # reported at commit time: every project must have a Dockerfile
    by_path = {c.file: c for c in changes}
    for path, text in containerize.docker_files(spec, contents, design.project_name, design.port, design.preview).items():
        if path in existing:
            continue
        patch = make_new_file_diff(path, text)
        if path in by_path:
            by_path[path].patch = patch  # e.g. README with the Docker section appended
        else:
            changes.append(ProposedChangeItem(file=path, operation="create", reason="Containerization (Docker).",
                                              patch=patch, confidence=0.8, risks=[], acceptance_criterion=""))
