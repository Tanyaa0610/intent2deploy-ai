"""Failure diagnosis + bounded repair proposal (master spec §17).

Validation Failure -> collect logs -> retrieve relevant code -> LLM
failure diagnosis -> repair proposal -> (human approval happens in the
orchestrator, not here) -> apply -> re-run validation.

MAX_REPAIR_ATTEMPTS is enforced by the caller (the orchestrator), not
here — this module only proposes a single repair given one failure.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.llm_reliability import structured_call
from app.core.prompts import load_prompt
from app.schemas.repair import RepairProposal
from app.services.providers.base import LLMProvider
from app.services.rag.formatting import format_retrieved_context
from app.services.rag.retriever import RetrievalResult


class _Diagnosis(BaseModel):
    diagnosis: str
    likely_root_cause: str
    affected_files: list[str] = Field(default_factory=list)


@dataclass
class DiagnosisResult:
    diagnosis: str
    root_cause: str
    affected_files: list[str]
    prompt_version: str


def diagnose_failure(
    provider: LLMProvider, stage: str, stdout: str, stderr: str, retrieved: list[RetrievalResult]
) -> DiagnosisResult:
    prompt = load_prompt("failure_diagnosis")
    context_text = format_retrieved_context(retrieved)
    rendered = prompt.render(stage=stage, stdout=stdout[-4000:], stderr=stderr[-4000:], retrieved_context=context_text)
    result = structured_call(
        provider,
        "failure_diagnosis",
        rendered,
        {"stage": stage, "stdout": stdout, "stderr": stderr, "affected_files": [r.file for r in retrieved]},
        schema=_Diagnosis,
    )
    return DiagnosisResult(
        diagnosis=result.parsed.diagnosis,
        root_cause=result.parsed.likely_root_cause,
        affected_files=result.parsed.affected_files,
        prompt_version=prompt.version,
    )


@dataclass
class RepairProposalResult:
    proposal: RepairProposal
    prompt_version: str
    raw_llm_output: str


def propose_repair(
    provider: LLMProvider, diagnosis: DiagnosisResult, retrieved: list[RetrievalResult]
) -> RepairProposalResult:
    prompt = load_prompt("repair_planning")
    context_text = format_retrieved_context(retrieved)
    rendered = prompt.render(diagnosis=diagnosis.diagnosis, root_cause=diagnosis.root_cause, retrieved_context=context_text)
    result = structured_call(
        provider,
        "repair_planning",
        rendered,
        {"diagnosis": diagnosis.diagnosis, "root_cause": diagnosis.root_cause},
        schema=RepairProposal,
    )
    return RepairProposalResult(proposal=result.parsed, prompt_version=prompt.version, raw_llm_output=result.raw_text)
