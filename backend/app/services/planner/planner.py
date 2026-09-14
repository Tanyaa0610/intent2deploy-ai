"""LLM planning service (master spec §10):

Developer Intent + Repository Context + Repository Metadata -> strict-JSON
plan, validated against PlanOutput, with every referenced file checked
against actual retrieval evidence (the planner must not invent files).
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.schemas.plan import PlanOutput
from app.services.providers.base import LLMProvider
from app.services.rag.formatting import format_retrieved_context, to_context_dicts
from app.services.rag.retriever import RetrievalResult, retrieve_multi


@dataclass
class PlanningResult:
    plan: PlanOutput
    retrieved: list[RetrievalResult]
    prompt_versions: dict[str, str]
    raw_llm_output: str
    invented_files_removed: list[str]


def generate_plan(provider: LLMProvider, collection_name: str, intent: str) -> PlanningResult:
    prompt_versions: dict[str, str] = {}

    # Stage 1: requirement analysis (normalize + surface assumptions)
    req_prompt = load_prompt("requirement_analysis")
    prompt_versions["requirement_analysis"] = req_prompt.version
    req_rendered = req_prompt.render(intent=intent)
    req_result = structured_call(
        provider, "requirement_analysis", req_rendered, {"intent": intent},
        schema=_RequirementAnalysis,
    )
    normalized_requirement = req_result.parsed.normalized_requirement

    # Stage 2: retrieval query expansion
    query_prompt = load_prompt("retrieval_query_generation")
    prompt_versions["retrieval_query_generation"] = query_prompt.version
    query_rendered = query_prompt.render(intent=intent, normalized_requirement=normalized_requirement)
    query_result = structured_call(
        provider,
        "retrieval_query_generation",
        query_rendered,
        {"intent": intent, "normalized_requirement": normalized_requirement},
        schema=_QueryList,
    )
    queries = query_result.parsed.queries or [intent]

    # Stage 3: hybrid retrieval across all expanded queries
    retrieved = retrieve_multi(collection_name, queries, top_k=12)
    retrieved_files = list(dict.fromkeys(r.file for r in retrieved))

    # Stage 4: implementation planning grounded in retrieved evidence
    plan_prompt = load_prompt("implementation_planning")
    prompt_versions["implementation_planning"] = plan_prompt.version
    context_text = format_retrieved_context(retrieved)
    plan_rendered = plan_prompt.render(
        intent=intent, retrieved_context=context_text, retrieved_files=retrieved_files
    )
    plan_result = structured_call(
        provider,
        "implementation_planning",
        plan_rendered,
        {"intent": intent, "retrieved": to_context_dicts(retrieved), "retrieved_files": retrieved_files},
        schema=PlanOutput,
    )
    plan = plan_result.parsed

    # Safety/evidence validation: strip any file the planner referenced
    # that was not actually retrieved (never invent repository files).
    retrieved_set = set(retrieved_files)
    invented: set[str] = set()
    for step in plan.steps:
        kept = [f for f in step.files if f in retrieved_set]
        invented.update(set(step.files) - retrieved_set)
        step.files = kept
    kept_files = [f for f in plan.files_likely_to_change if f in retrieved_set]
    invented.update(set(plan.files_likely_to_change) - retrieved_set)
    plan.files_likely_to_change = kept_files

    return PlanningResult(
        plan=plan,
        retrieved=retrieved,
        prompt_versions=prompt_versions,
        raw_llm_output=plan_result.raw_text,
        invented_files_removed=sorted(invented),
    )


# Small local schemas for the intermediate stages (not persisted directly).
class _RequirementAnalysis(BaseModel):
    normalized_requirement: str
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class _QueryList(BaseModel):
    queries: list[str] = Field(default_factory=list)
