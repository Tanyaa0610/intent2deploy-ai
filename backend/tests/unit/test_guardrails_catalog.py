"""Guardrail Control Plane catalog + record/enforce mechanics."""
from __future__ import annotations

from app.models.enums import GuardrailCategory, GuardrailStatus
from app.models.models import GuardrailCheck
from app.services.guardrails import engine as guardrails


def test_catalog_covers_all_8_categories_only():
    categories_in_catalog = {g["category"] for g in guardrails.GUARDRAIL_CATALOG}
    assert categories_in_catalog == {c.value for c in GuardrailCategory}
    assert len(categories_in_catalog) == 8


def test_catalog_has_no_old_g_prefixed_ids():
    for g in guardrails.GUARDRAIL_CATALOG:
        assert not g["guardrail_id"].startswith("G0")
        assert not g["guardrail_id"].startswith("G1")


def test_catalog_ids_are_unique():
    ids = [g["guardrail_id"] for g in guardrails.GUARDRAIL_CATALOG]
    assert len(ids) == len(set(ids))


def test_catalog_has_at_least_5_per_category():
    from collections import Counter

    counts = Counter(g["category"] for g in guardrails.GUARDRAIL_CATALOG)
    for category in GuardrailCategory:
        assert counts[category.value] >= 5, f"{category.value} has too few guardrails"


def test_enforce_raises_and_persists_on_block(db_session):
    result = guardrails.check_production_block("workflow_creation", "production")
    raised = False
    try:
        guardrails.enforce(db_session, "wf-does-not-exist", result)
    except guardrails.GuardrailBlockedError:
        raised = True
    assert raised

    from sqlmodel import select

    rows = db_session.exec(select(GuardrailCheck)).all()
    assert len(rows) == 1
    assert rows[0].status == GuardrailStatus.BLOCKED.value
    assert rows[0].guardrail_id == "DEPLOY-02"
    assert rows[0].category == "DEPLOYMENT"


def test_record_never_raises_even_when_blocked(db_session):
    result = guardrails.check_production_block("workflow_creation", "production")
    row = guardrails.record(db_session, "wf-does-not-exist", result)
    assert row.status == GuardrailStatus.BLOCKED.value
