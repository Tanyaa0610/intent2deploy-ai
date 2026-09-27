"""Production Simulation (Part G).

An in-memory, explicitly-sandboxed simulated service graph used by the
Production Simulation dashboard page. It never touches real infrastructure
or the actual demo-repository process — Guardrail 02 (Production
Environment Block) and Guardrail 11 (Chaos Safety Gate) both require that.
State lives in process memory and resets on backend restart; this is a
demo/teaching tool, not a monitoring system, and is labeled as such in the
UI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

SERVICES = ["api", "database", "external_payment_provider", "cache", "worker", "queue", "monitoring"]

INJECTABLE_FAULTS = {
    "inject_timeout": "timeout",
    "inject_5xx": "5xx",
    "inject_latency": "latency",
    "stop_dependency": "stopped",
    "simulate_load": "high_load",
    "restore_dependency": None,
}


@dataclass
class ServiceState:
    name: str
    health: str = "healthy"  # healthy | degraded | down
    latency_ms: int = 20
    error_rate: float = 0.0
    request_volume: int = 100
    active_fault: str | None = None


@dataclass
class SimulationState:
    services: dict[str, ServiceState] = field(default_factory=lambda: {s: ServiceState(name=s) for s in SERVICES})
    history: list[dict] = field(default_factory=list)


_state = SimulationState()


def get_state() -> SimulationState:
    return _state


def reset() -> SimulationState:
    global _state
    _state = SimulationState()
    return _state


def _log(service: str, action: str, detail: str) -> None:
    _state.history.append({"timestamp": time.time(), "service": service, "action": action, "detail": detail})


def inject_fault(service: str, action: str) -> ServiceState:
    if service not in _state.services:
        raise ValueError(f"Unknown simulated service '{service}'. Known services: {SERVICES}")
    if action not in INJECTABLE_FAULTS:
        raise ValueError(f"Unknown simulation action '{action}'. Known actions: {list(INJECTABLE_FAULTS)}")

    svc = _state.services[service]
    if action == "inject_timeout":
        svc.health = "degraded"
        svc.latency_ms = 30000
        svc.active_fault = "timeout"
    elif action == "inject_5xx":
        svc.health = "degraded"
        svc.error_rate = 0.8
        svc.active_fault = "5xx"
    elif action == "inject_latency":
        svc.health = "degraded"
        svc.latency_ms = max(svc.latency_ms, 2000)
        svc.active_fault = "latency"
    elif action == "stop_dependency":
        svc.health = "down"
        svc.error_rate = 1.0
        svc.active_fault = "stopped"
    elif action == "simulate_load":
        svc.request_volume *= 10
        svc.latency_ms = int(svc.latency_ms * 1.5)
        svc.health = "degraded" if svc.latency_ms > 500 else svc.health
        svc.active_fault = "high_load"
    elif action == "restore_dependency":
        svc.health = "healthy"
        svc.latency_ms = 20
        svc.error_rate = 0.0
        svc.request_volume = 100
        svc.active_fault = None

    _log(service, action, f"{service} -> health={svc.health}, latency_ms={svc.latency_ms}, error_rate={svc.error_rate}")
    return svc
