"""Production Simulation (Part G) — a sandboxed, in-memory simulated
service graph. Never touches real infrastructure (Guardrail 02/11)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.simulation import engine as sim

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


class InjectRequest(BaseModel):
    service: str
    action: str


def _state_to_dict() -> dict:
    state = sim.get_state()
    return {
        "services": {
            name: {
                "name": s.name,
                "health": s.health,
                "latency_ms": s.latency_ms,
                "error_rate": s.error_rate,
                "request_volume": s.request_volume,
                "active_fault": s.active_fault,
            }
            for name, s in state.services.items()
        },
        "history": state.history[-50:],
    }


@router.get("/state")
def get_state() -> dict:
    return _state_to_dict()


@router.post("/inject")
def inject(payload: InjectRequest) -> dict:
    try:
        sim.inject_fault(payload.service, payload.action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _state_to_dict()


@router.post("/reset")
def reset() -> dict:
    sim.reset()
    return _state_to_dict()
