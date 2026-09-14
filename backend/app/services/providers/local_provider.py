"""Deterministic mock LLM provider (LLM_MODE=mock).

Performs real retrieval-grounded synthesis for each prompt category (see
module docstrings in app/services/planner/intent_classifier.py and
app/services/codegen/mock_strategies.py for the honesty rationale). No
network calls, no API key required.
"""
from __future__ import annotations

import json

from app.services.codegen import mock_strategies
from app.services.planner.category_metadata import CATEGORY_METADATA
from app.services.planner.intent_classifier import classify_intent, extract_key_terms
from app.services.providers.base import LLMProvider, LLMResponse, LLMUsage
from app.services.testing import mock_test_strategies


class LocalProvider(LLMProvider):
    name = "local"

    @property
    def is_mock(self) -> bool:
        return True

    def complete(self, prompt_name: str, rendered_prompt: str, context: dict) -> LLMResponse:
        handler = getattr(self, f"_handle_{prompt_name}", None)
        if handler is None:
            raise ValueError(f"LocalProvider has no mock handler for prompt '{prompt_name}'")
        text = handler(context)
        return LLMResponse(
            text=text,
            usage=LLMUsage(available=False),
            model="local-mock-v1",
            provider=self.name,
            is_mock=True,
        )

    # ------------------------------------------------------------------
    def _handle_requirement_analysis(self, context: dict) -> str:
        intent = context["intent"]
        terms = extract_key_terms(intent)
        normalized = intent.strip().rstrip(".") + "."
        assumptions = [
            "Existing behavior not explicitly mentioned in the intent should remain unchanged.",
        ]
        if "test" not in intent.lower():
            assumptions.append("New tests should be added even though the intent did not explicitly request them.")
        return json.dumps(
            {
                "normalized_requirement": normalized,
                "assumptions": assumptions,
                "open_questions": [
                    f"Should '{terms[0]}' behavior be feature-flagged or always-on?" if terms else
                    "Are there any non-functional requirements (performance, security) beyond correctness?",
                ],
            }
        )

    def _handle_retrieval_query_generation(self, context: dict) -> str:
        intent = context["intent"]
        normalized = context.get("normalized_requirement", intent)
        queries = [
            intent,
            normalized,
            f"existing tests related to: {intent}",
            f"configuration or dependencies related to: {intent}",
        ]
        return json.dumps({"queries": queries})

    def _handle_code_explanation(self, context: dict) -> str:
        retrieved: list[dict] = context.get("retrieved", [])
        if not retrieved:
            return json.dumps(
                {
                    "answer": "No relevant repository content was retrieved for this question. "
                    "Try rephrasing, or index the repository first.",
                    "cited_files": [],
                }
            )
        top = retrieved[0]
        cited = list(dict.fromkeys(r["file"] for r in retrieved[:3]))
        symbol_note = f" (symbol: {top['symbol']})" if top.get("symbol") else ""
        answer = (
            f"Based on the retrieved evidence, the most relevant location is "
            f"{top['file']}:{top['start_line']}-{top['end_line']}{symbol_note}. "
            f"{top['reason']}. Preview: {top['content_preview'][:220].strip()}"
        )
        return json.dumps({"answer": answer, "cited_files": cited})

    def _handle_implementation_planning(self, context: dict) -> str:
        intent = context["intent"]
        retrieved_files: list[str] = context.get("retrieved_files", [])
        category = classify_intent(intent)
        meta = CATEGORY_METADATA.get(category, CATEGORY_METADATA["generic"])

        files_likely = [f for f in retrieved_files if f][:5]
        primary_file = meta.get("primary_file", "")
        if primary_file and primary_file in retrieved_files and primary_file not in files_likely:
            files_likely = [primary_file] + files_likely[:4]
        steps = []
        for i, f in enumerate(files_likely, start=1):
            steps.append(
                {
                    "id": f"S{i}",
                    "description": f"Update {f} to implement: {meta['summary']}",
                    "files": [f],
                }
            )
        if not steps:
            steps = [{"id": "S1", "description": "No repository evidence retrieved; manual investigation required.", "files": []}]

        plan = {
            "summary": meta["summary"],
            "assumptions": [
                "The retrieved files below represent the relevant existing implementation.",
            ],
            "acceptance_criteria": meta["acceptance_criteria"],
            "steps": steps,
            "files_likely_to_change": files_likely,
            "dependencies": [],
            "test_strategy": meta["test_strategy"],
            "risks": meta["risks"],
        }
        return json.dumps(plan)

    def _handle_code_modification(self, context: dict) -> str:
        intent = context["intent"]
        file_contents: dict[str, str] = context.get("file_contents", {})
        category = classify_intent(intent)
        strategy = mock_strategies.STRATEGIES.get(category)
        mock_changes = strategy(file_contents) if strategy else []

        changes = [
            {
                "file": c.file,
                "operation": c.operation,
                "reason": c.reason,
                "patch": c.patch,
                "confidence": c.confidence,
                "risks": c.risks,
                "acceptance_criterion": c.acceptance_criterion,
            }
            for c in mock_changes
        ]
        if not changes:
            changes = [
                {
                    "file": next(iter(file_contents), "UNKNOWN"),
                    "operation": "modify",
                    "reason": (
                        "Mock mode (LLM_MODE=mock) has no grounded code-generation strategy "
                        "for this intent category. No change is proposed; switch to "
                        "LLM_MODE=live with a configured provider for general-purpose "
                        "code generation."
                    ),
                    "patch": "",
                    "confidence": 0.0,
                    "risks": ["No automated change generated in mock mode for this intent."],
                    "acceptance_criterion": "",
                }
            ]
        return json.dumps({"changes": changes})

    def _handle_test_generation(self, context: dict) -> str:
        intent = context["intent"]
        category = classify_intent(intent)
        strategy = mock_test_strategies.STRATEGIES.get(category)
        mock_tests = strategy() if strategy else []
        tests = [
            {"file": t.file, "content": t.content, "rationale": t.rationale, "category": t.category}
            for t in mock_tests
        ]
        return json.dumps(
            {
                "tests": tests,
                "existing_tests_found": context.get("existing_tests_found", 0),
                "relevant_tests": context.get("relevant_tests", 0),
            }
        )

    def _handle_failure_diagnosis(self, context: dict) -> str:
        stderr = context.get("stderr", "")
        stage = context.get("stage", "unknown")
        last_lines = "\n".join(stderr.strip().splitlines()[-5:]) if stderr else "(no stderr captured)"
        return json.dumps(
            {
                "diagnosis": f"The '{stage}' stage failed. Last captured error output: {last_lines[:500]}",
                "likely_root_cause": last_lines[:300] or "Unknown; no stderr was captured.",
                "affected_files": context.get("affected_files", []),
            }
        )

    def _handle_repair_planning(self, context: dict) -> str:
        return json.dumps(
            {
                "diagnosis": context.get("diagnosis", ""),
                "root_cause": context.get("root_cause", ""),
                "repair_patch": "",
                "confidence": 0.0,
                "files": [],
            }
        )

    def _handle_final_report_generation(self, context: dict) -> str:
        trace = context.get("workflow_trace", {})
        status = trace.get("final_status", "UNKNOWN")
        approvals = trace.get("human_intervention_count", 0)
        repairs = trace.get("repair_attempts", 0)
        summary = (
            f"Workflow for intent '{trace.get('intent', '')[:80]}' finished with status {status}. "
            f"{approvals} human approval action(s) were recorded and {repairs} repair attempt(s) were made."
        )
        return json.dumps({"executive_summary": summary})
