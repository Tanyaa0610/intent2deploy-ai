from __future__ import annotations

from app.models.enums import Severity
from app.services.risk.engine import derive_risks, highest_severity, risk_distribution


def test_derive_risks_from_plan_and_category_and_static_scan():
    risks = derive_risks(
        plan_risks=["Authentication regression risk"],
        category_risks=["Reset tokens are stored in-memory"],
        changed_files=["src/payments/service.py"],
        acceptance_criteria=["User can request a password reset"],
    )
    sources = {r.source for r in risks}
    assert "llm_plan" in sources
    assert "category_metadata" in sources
    assert "static_scan" in sources
    assert any("payment" in r.title.lower() for r in risks)


def test_derive_risks_deduplicates_identical_titles():
    risks = derive_risks(
        plan_risks=["Same risk text"],
        category_risks=["Same risk text"],
        changed_files=[],
        acceptance_criteria=[],
    )
    assert len(risks) == 1


def test_severity_classification_prioritizes_critical_keywords():
    risks = derive_risks(
        plan_risks=["Duplicate charge on payment provider timeout is a financial risk"],
        category_risks=[],
        changed_files=[],
        acceptance_criteria=[],
    )
    assert risks[0].severity == Severity.CRITICAL.value


def test_risk_distribution_and_highest_severity():
    risks = derive_risks(
        plan_risks=["payment duplicate charge risk", "auth token regression risk", "generic minor risk"],
        category_risks=[],
        changed_files=[],
        acceptance_criteria=[],
    )
    dist = risk_distribution(risks)
    assert sum(dist.values()) == len(risks)
    assert highest_severity(risks) == Severity.CRITICAL.value
    assert highest_severity([]) is None
