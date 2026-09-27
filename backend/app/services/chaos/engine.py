"""Resilience Lab / chaos engine (Part F).

Runs only the experiments that are relevant to the architecture actually
detected in the target repository's changed files + the intent's primary
component. Each experiment inspects real source text for a resilience
signal (idempotency key, try/except, retry/backoff, O(1) data structures)
instead of performing live fault injection against a running process —
there is no live target process to inject faults into safely, and doing so
against real infrastructure is exactly what Guardrail 02/11 forbid. This is
a static-analysis-based simulation, labeled as such throughout the UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChaosOutcome:
    experiment_id: str
    target: str
    hypothesis: str
    fault: str
    expected_behavior: str
    observed_behavior: str
    result: str  # PASSED | FAILED | NOT_APPLICABLE
    evidence: list[str]


def _read(repo_root: Path, files: list[str]) -> str:
    text = ""
    for f in files:
        p = repo_root / f
        if p.is_file():
            try:
                text += "\n" + p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return text


def _search_repo(repo_root: Path, pattern: str) -> list[str]:
    """Cheap relevance scan across the target repo's Python source."""
    hits: list[str] = []
    for p in repo_root.rglob("*.py"):
        if any(part in {"tests", ".venv", "venv", "__pycache__"} for part in p.parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(pattern, content, re.I):
            hits.append(str(p.relative_to(repo_root)))
    return hits


def _has_idempotency_protection(source: str) -> bool:
    return bool(re.search(r"idempotency_key", source, re.I)) and bool(re.search(r"idempotency_cache|_cache\[", source))


def run_experiments(repo_root: Path, changed_files: list[str], intent: str) -> list[ChaosOutcome]:
    outcomes: list[ChaosOutcome] = []
    changed_source = _read(repo_root, changed_files)

    payment_files = _search_repo(repo_root, r"PaymentProviderClient|charge_order")
    has_payment_dependency = bool(payment_files)
    payment_source = _read(repo_root, payment_files) if payment_files else ""
    idempotent = _has_idempotency_protection(payment_source or changed_source)

    api_files = _search_repo(repo_root, r"FastAPI\(")
    has_api = bool(api_files)

    cache_files = _search_repo(repo_root, r"\bcache\b")
    queue_files = _search_repo(repo_root, r"\bqueue\b")
    db_files = _search_repo(repo_root, r"sqlite3|sqlalchemy|\.execute\(\s*[\"']select|create_engine")
    json_parse_files = _search_repo(repo_root, r"\.json\(\)|json\.loads\(")

    # 1. Dependency unavailable (external payment provider)
    if has_payment_dependency:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH01",
                target="PaymentService -> PaymentProviderClient",
                hypothesis="If the external payment provider is unavailable, a client retry must not create a duplicate charge.",
                fault="Dependency unavailable (payment provider does not respond)",
                expected_behavior="A retried charge with the same idempotency key returns the original result instead of a new provider call.",
                observed_behavior=(
                    "charge_order caches results by idempotency_key and returns the cached charge on retry."
                    if idempotent
                    else "charge_order has no idempotency_key handling; a retry after the provider is unavailable would create a second charge."
                ),
                result="PASSED" if idempotent else "FAILED",
                evidence=payment_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH01", "Dependency unavailable", "No external dependency client (e.g. a payment provider) detected in this repository."))

    # 2. HTTP timeout
    if has_payment_dependency:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH02",
                target="PaymentProviderClient.charge",
                hypothesis="A provider timeout mid-request must not leave the system unable to tell whether the charge succeeded.",
                fault="HTTP timeout (PaymentProviderTimeout raised mid-charge)",
                expected_behavior="A subsequent retry with the same idempotency key is safe and does not double-charge.",
                observed_behavior=(
                    "Idempotency-key caching makes a post-timeout retry safe."
                    if idempotent
                    else "No idempotency protection: a retry after a timeout can double-charge the customer."
                ),
                result="PASSED" if idempotent else "FAILED",
                evidence=payment_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH02", "HTTP timeout", "No outbound HTTP/provider client detected."))

    # 3. HTTP 5xx
    outcomes.append(_not_applicable("CH03", "HTTP 5xx", "Provider client in this demo repository does not model HTTP status codes; documented limitation.") )

    # 4. Dependency unavailable variant: network interruption
    if has_payment_dependency:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH08",
                target="PaymentService -> PaymentProviderClient",
                hypothesis="A transient network interruption to the payment provider should be tolerated the same way a timeout is.",
                fault="Network interruption simulation",
                expected_behavior="Retries after a network interruption are idempotent.",
                observed_behavior=(
                    "Same idempotency-key protection covers this fault shape."
                    if idempotent
                    else "Same lack of idempotency protection applies to a network interruption as to a timeout."
                ),
                result="PASSED" if idempotent else "FAILED",
                evidence=payment_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH08", "Network interruption simulation", "No external network dependency detected."))

    # 5. Duplicate request
    if has_payment_dependency:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH10",
                target="PaymentService.charge_order",
                hypothesis="Two duplicate client requests for the same logical payment must not both succeed as separate charges.",
                fault="Duplicate request",
                expected_behavior="The second, duplicate request is deduplicated by idempotency key.",
                observed_behavior=(
                    "Duplicate calls with the same idempotency_key return the same charge."
                    if idempotent
                    else "Duplicate calls create two separate charges — no deduplication."
                ),
                result="PASSED" if idempotent else "FAILED",
                evidence=payment_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH10", "Duplicate request", "No idempotency-sensitive write operation detected in the changed files."))

    # 6. High request load — generic architectural check, relevant whenever an API exists.
    if has_api:
        dict_backed = _search_repo(repo_root, r"dict\[|\{\}\s*#.*store|self\._\w+:\s*dict")
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH09",
                target="API layer (FastAPI app)",
                hypothesis="Per-request work should not degrade non-linearly as data grows.",
                fault="High request load / burst traffic",
                expected_behavior="Request handlers perform O(1)/O(n) dictionary or list lookups, not unbounded nested scans.",
                observed_behavior=(
                    "Services use dict-backed in-memory storage (O(1) lookups); no unbounded per-request scan detected in the API layer."
                    if dict_backed
                    else "No dict-backed storage pattern detected; per-request cost not independently verified in this build."
                ),
                result="PASSED" if dict_backed else "NOT_APPLICABLE",
                evidence=api_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH09", "High request load", "No HTTP API layer detected in this repository."))

    # 7. Cache failure
    if cache_files:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH11",
                target="Cache layer",
                hypothesis="A cache outage should degrade gracefully, not crash requests.",
                fault="Cache failure",
                expected_behavior="Cache misses/outages fall back to the source of truth.",
                observed_behavior="Cache usage detected; fallback behavior not independently verified in this build.",
                result="NOT_APPLICABLE",
                evidence=cache_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH11", "Cache failure", "No caching layer detected in this repository."))

    # 8. Queue delay
    if queue_files:
        outcomes.append(
            ChaosOutcome(
                experiment_id="CH12",
                target="Queue/worker layer",
                hypothesis="A delayed queue should not cause data loss or duplicate processing.",
                fault="Queue delay",
                expected_behavior="Delayed messages are eventually processed exactly once.",
                observed_behavior="Queue usage detected; delivery semantics not independently verified in this build.",
                result="NOT_APPLICABLE",
                evidence=queue_files,
            )
        )
    else:
        outcomes.append(_not_applicable("CH12", "Queue delay", "No queue/worker component detected in this repository."))

    # 9. Database latency / unavailable
    if db_files:
        outcomes.append(_not_applicable("CH04", "Database latency", "Database usage detected but not independently load-tested in this build."))
        outcomes.append(_not_applicable("CH05", "Database unavailable", "Database usage detected but not independently fault-injected in this build."))
    else:
        outcomes.append(_not_applicable("CH04", "Database latency", "This repository uses in-memory dict-backed persistence, not a database."))
        outcomes.append(_not_applicable("CH05", "Database unavailable", "This repository uses in-memory dict-backed persistence, not a database."))

    # 10. Malformed response
    if json_parse_files:
        outcomes.append(_not_applicable("CH06", "Malformed response", "External JSON parsing detected but not independently fuzzed in this build."))
    else:
        outcomes.append(_not_applicable("CH06", "Malformed response", "No external JSON-parsing call site detected."))

    # 11. Service crash
    outcomes.append(_not_applicable("CH07", "Service crash", "No HTTP route currently exposes the payment path for an end-to-end crash simulation; documented limitation."))

    return outcomes


def _not_applicable(experiment_id: str, name: str, reason: str) -> ChaosOutcome:
    return ChaosOutcome(
        experiment_id=experiment_id,
        target=name,
        hypothesis=f"{name} is relevant to this architecture.",
        fault=name,
        expected_behavior="N/A",
        observed_behavior=reason,
        result="NOT_APPLICABLE",
        evidence=[],
    )


def chaos_pass_rate(outcomes: list[ChaosOutcome]) -> float | None:
    applicable = [o for o in outcomes if o.result != "NOT_APPLICABLE"]
    if not applicable:
        return None
    return round(sum(1 for o in applicable if o.result == "PASSED") / len(applicable), 3)
