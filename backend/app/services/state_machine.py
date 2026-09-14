"""Workflow state machine enforcement (master spec §30)."""
from __future__ import annotations

from app.models.enums import ALLOWED_TRANSITIONS, WorkflowState


class InvalidTransitionError(Exception):
    pass


def transition(current: WorkflowState, target: WorkflowState) -> WorkflowState:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(f"Cannot transition from {current.value} to {target.value}.")
    return target
