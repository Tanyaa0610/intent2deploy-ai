"""Production risk engine (Part C).

Builds `RiskItem` rows from three real evidence sources only — never
invents a risk that isn't traceable to one of them:

1. the LLM plan's own `risks` list (source="llm_plan")
2. the intent category's known risk metadata (source="category_metadata")
3. a static scan of the proposed changes' file paths for
   auth/payment/database-shaped components (source="static_scan")
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.enums import Severity

_SEVERITY_KEYWORDS: list[tuple[str, str]] = [
    (Severity.CRITICAL.value, r"payment|charge|money|financial|data ?loss|security vulnerab|credential|migrat"),
    (Severity.HIGH.value, r"auth|token|session|password|regression|duplicate|race condition|concurren"),
    (Severity.MEDIUM.value, r"performance|latency|timeout|deprecat|compat"),
]

_COMPONENT_KEYWORDS: list[tuple[str, str]] = [
    ("payments", r"payment"),
    ("authentication", r"auth"),
    ("orders", r"order"),
    ("users", r"user"),
    ("database", r"db|database|migrat|sql"),
    ("api", r"api|endpoint|route"),
    ("validation", r"valid"),
]


@dataclass
class DerivedRisk:
    risk_id: str
    title: str
    component: str
    severity: str
    likelihood: str
    blast_radius: str
    detection: str
    mitigation: str
    validation_method: str
    status: str
    evidence: list[str]
    source: str


def _classify_severity(text: str) -> str:
    lowered = text.lower()
    for severity, pattern in _SEVERITY_KEYWORDS:
        if re.search(pattern, lowered):
            return severity
    return Severity.LOW.value


def _classify_component(text: str, changed_files: list[str]) -> str:
    lowered = (text + " " + " ".join(changed_files)).lower()
    for component, pattern in _COMPONENT_KEYWORDS:
        if re.search(pattern, lowered):
            return component
    return "general"


def derive_risks(
    plan_risks: list[str],
    category_risks: list[str],
    changed_files: list[str],
    acceptance_criteria: list[str],
) -> list[DerivedRisk]:
    risks: list[DerivedRisk] = []
    seen_titles: set[str] = set()
    counter = 1

    def _add(title: str, source: str, evidence: list[str]) -> None:
        nonlocal counter
        key = title.strip().lower()
        if not title.strip() or key in seen_titles:
            return
        seen_titles.add(key)
        severity = _classify_severity(title)
        component = _classify_component(title, changed_files)
        likelihood = Severity.HIGH.value if source == "static_scan" else Severity.MEDIUM.value
        blast_radius = f"{len(changed_files)} file(s): {', '.join(changed_files) or 'unknown'}"
        risks.append(
            DerivedRisk(
                risk_id=f"R{counter}",
                title=title,
                component=component,
                severity=severity,
                likelihood=likelihood,
                blast_radius=blast_radius,
                detection="Automated validation pipeline (lint/tests/build/security) + resilience/chaos simulation" if severity in (Severity.HIGH.value, Severity.CRITICAL.value) else "Automated validation pipeline",
                mitigation="Human review required before commit; acceptance criteria: " + "; ".join(acceptance_criteria[:2]) if acceptance_criteria else "Human review required before commit.",
                validation_method="unit_tests + resilience_tests" if severity in (Severity.HIGH.value, Severity.CRITICAL.value) else "unit_tests",
                status="OPEN",
                evidence=evidence,
                source=source,
            )
        )
        counter += 1

    for r in plan_risks:
        _add(r, "llm_plan", [f"Stated in LLM-generated implementation plan: {r!r}"])
    for r in category_risks:
        _add(r, "category_metadata", ["Known risk pattern for this intent category."])

    # Static scan: flag components touched that carry structurally higher risk.
    for f in changed_files:
        lowered = f.lower()
        if "payment" in lowered:
            _add(
                "Change touches payment-processing code; duplicate charges or lost transactions on provider timeout are a direct financial risk.",
                "static_scan",
                [f"Proposed change modifies {f}"],
            )
        if "auth" in lowered:
            _add(
                "Change touches authentication code; a defect could allow unauthorized access or lock out legitimate users.",
                "static_scan",
                [f"Proposed change modifies {f}"],
            )
        if "migrat" in lowered or lowered.endswith(".sql"):
            _add(
                "Change includes a database migration; irreversible schema/data changes carry data-loss risk.",
                "static_scan",
                [f"Proposed change modifies {f}"],
            )

    return risks


def risk_distribution(risks: list[DerivedRisk]) -> dict[str, int]:
    dist = {s.value: 0 for s in Severity}
    for r in risks:
        dist[r.severity] = dist.get(r.severity, 0) + 1
    return dist


def highest_severity(risks: list[DerivedRisk]) -> str | None:
    order = [Severity.CRITICAL.value, Severity.HIGH.value, Severity.MEDIUM.value, Severity.LOW.value]
    present = {r.severity for r in risks}
    for level in order:
        if level in present:
            return level
    return None
