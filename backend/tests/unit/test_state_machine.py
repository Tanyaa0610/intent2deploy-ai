import pytest

from app.models.enums import WorkflowState
from app.services.state_machine import InvalidTransitionError, transition


def test_valid_transition_allowed():
    assert transition(WorkflowState.CREATED, WorkflowState.INDEXING) == WorkflowState.INDEXING


def test_invalid_transition_rejected():
    with pytest.raises(InvalidTransitionError):
        transition(WorkflowState.CREATED, WorkflowState.COMPLETED)


def test_terminal_states_have_no_outgoing_transitions():
    with pytest.raises(InvalidTransitionError):
        transition(WorkflowState.COMPLETED, WorkflowState.CREATED)
    with pytest.raises(InvalidTransitionError):
        transition(WorkflowState.FAILED, WorkflowState.CREATED)


def test_plan_rejection_path():
    assert transition(WorkflowState.AWAITING_PLAN_APPROVAL, WorkflowState.PLAN_REJECTED) == WorkflowState.PLAN_REJECTED
    assert transition(WorkflowState.PLAN_REJECTED, WorkflowState.PLANNING) == WorkflowState.PLANNING
