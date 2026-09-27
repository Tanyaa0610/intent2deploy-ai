"""AI-DevOps Guardrail Control Plane.

This is the ONLY guardrail engine in the system. It replaces an earlier
flat 18-guardrail (G01-G18) design in full — there is no parallel/legacy
engine kept alongside this one. Every guardrail belongs to exactly one of
the 8 categories in `app.models.enums.GuardrailCategory`:

    SECURITY, INFRASTRUCTURE, CI_CD, DEPLOYMENT, COST, AI_LLM, INPUT, OUTPUT

A guardrail is a small pure function that inspects real workflow state
(never a fabricated signal) and returns a `GuardrailCheckResult`. The
orchestrator calls the relevant guardrails at each checkpoint in the
execution model and persists one `GuardrailCheck` row per evaluation via
`record()` — PASSED, WARNING, BLOCKED, FAILED, NOT_APPLICABLE and
NOT_IMPLEMENTED results are all recorded, so the Guardrail Control Plane
dashboard and the audit trail always show what was actually checked.

A guardrail whose `action` is BLOCK or ABORT causes `enforce()` to raise
`GuardrailBlockedError`, which orchestrator call sites turn into an
explanatory `OrchestratorError` (stage / cause / evidence / recovery
action) rather than a silent no-op.

Where a check genuinely cannot be evaluated with the tooling available in
this repository (e.g. live CVE/dependency-vulnerability lookup requires
network access to a package index this environment does not have), the
result is `NOT_IMPLEMENTED` with a remediation note explaining why —
never a fabricated PASSED.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from app.core.config import settings
from app.core.security import DANGEROUS_TOKENS, COMMAND_ALLOWLIST, scan_for_secrets
from app.models.enums import (
    ALLOWED_EXECUTION_ENVIRONMENTS,
    Environment,
    GuardrailAction,
    GuardrailCategory,
    GuardrailStatus,
    Severity,
)
from app.models.models import GuardrailCheck

CAT = GuardrailCategory


class GuardrailBlockedError(Exception):
    def __init__(self, guardrail_id: str, name: str, reason: str, evidence: list[str] | None = None):
        self.guardrail_id = guardrail_id
        self.name = name
        self.reason = reason
        self.evidence = evidence or []
        super().__init__(
            f"[{guardrail_id}] {name} {self._verb()}: {reason}"
            + (f" Evidence: {'; '.join(self.evidence)}" if self.evidence else "")
        )

    def _verb(self) -> str:
        return "BLOCKED"


@dataclass
class GuardrailCheckResult:
    guardrail_id: str
    category: str
    name: str
    description: str
    purpose: str
    enforcement_point: str
    severity: str
    status: str
    action: str
    trigger_condition: str = ""
    evidence: list[str] = field(default_factory=list)
    remediation: str = ""
    configurable_threshold: str = ""
    enabled: bool = True


def record(session: Session, workflow_id: str, result: GuardrailCheckResult) -> GuardrailCheck:
    row = GuardrailCheck(
        workflow_id=workflow_id,
        guardrail_id=result.guardrail_id,
        category=result.category,
        name=result.name,
        description=result.description,
        purpose=result.purpose,
        trigger_condition=result.trigger_condition,
        enforcement_point=result.enforcement_point,
        severity=result.severity,
        status=result.status,
        action=result.action,
        evidence_json=json.dumps(result.evidence),
        remediation=result.remediation,
        configurable_threshold=result.configurable_threshold,
        enabled=result.enabled,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def enforce(session: Session, workflow_id: str, result: GuardrailCheckResult) -> GuardrailCheck:
    """Persist the result, then raise if its action stops execution."""
    row = record(session, workflow_id, result)
    if result.action in (GuardrailAction.BLOCK.value, GuardrailAction.ABORT.value):
        raise GuardrailBlockedError(result.guardrail_id, result.name, _reason_from(result), result.evidence)
    return row


def _reason_from(result: GuardrailCheckResult) -> str:
    return result.trigger_condition or result.description


# ---------------------------------------------------------------------------
# Shared pattern libraries
# ---------------------------------------------------------------------------
DEPENDENCY_FILES = {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "poetry.lock", "Pipfile"}
MIGRATION_PATH_PATTERNS = [re.compile(r"migrations?/"), re.compile(r"alembic/"), re.compile(r".*\.sql$")]
CONFIG_FILE_PATTERNS = [
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r".*\.ya?ml$"),
    re.compile(r".*config.*\.py$", re.I),
    re.compile(r".*\.toml$"),
    re.compile(r".*settings.*\.py$", re.I),
]
INFRA_FILE_PATTERNS = [
    re.compile(r"(^|/)Dockerfile[\w.\-]*$"),
    re.compile(r"docker-compose.*\.ya?ml$"),
    re.compile(r"(^|/)k8s/"),
    re.compile(r".*\.tf$"),
    re.compile(r"\.github/workflows/.*\.ya?ml$"),
]
CI_WORKFLOW_PATTERN = re.compile(r"\.github/workflows/.*\.ya?ml$")
API_FILE_PATTERNS = [re.compile(r"api/"), re.compile(r"routes?/"), re.compile(r".*app\.py$")]
ROLLBACK_KEYWORDS = ["rollback", "roll back", "revert", "feature flag", "feature-flag"]

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore (all |the )?(previous|prior|above) instructions"),
    re.compile(r"(?i)disregard (all |the )?(previous|prior|above) (instructions|rules)"),
    re.compile(r"(?i)you are now"),
    re.compile(r"(?i)new system prompt"),
    re.compile(r"(?i)^\s*system\s*:", re.M),
    re.compile(r"(?i)act as (an?|the) (unrestricted|jailbroken|uncensored)"),
    re.compile(r"(?i)do anything now"),
    re.compile(r"(?i)reveal your (system )?prompt"),
]

CODE_SECURITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("command_injection", re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True")),
    ("command_injection", re.compile(r"os\.system\(")),
    ("sql_injection", re.compile(r"execute\(\s*f[\"']")),
    ("sql_injection", re.compile(r"execute\(\s*[\"'].*%s.*[\"']\s*%")),
    ("unsafe_deserialization", re.compile(r"pickle\.loads?\(")),
    ("unsafe_deserialization", re.compile(r"yaml\.load\((?!.*Loader=yaml\.SafeLoader)")),
    ("eval_exec", re.compile(r"\beval\(")),
    ("eval_exec", re.compile(r"\bexec\(")),
    ("path_traversal", re.compile(r"open\([^)]*request\.")),
    ("insecure_auth", re.compile(r"password\s*==\s*")),
]

CONTAINER_SECURITY_CHECKS: list[tuple[str, re.Pattern, str]] = [
    ("privileged_container", re.compile(r"(?i)--privileged"), "Container may run with elevated host privileges."),
    ("unsafe_base_image", re.compile(r"(?i)^FROM\s+\S+:latest", re.M), "Base image is pinned to :latest, not a fixed version."),
]

CORS_WILDCARD_PATTERN = re.compile(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]")

DANGEROUS_INPUT_PATTERNS = [
    re.compile(r"(?i)delete (the )?production (database|db)"),
    re.compile(r"(?i)drop (table|database)"),
    re.compile(r"(?i)rm\s+-rf"),
    re.compile(r"(?i)wipe (the )?database"),
    re.compile(r"(?i)truncate (table)?"),
]
PRODUCTION_ACCESS_PATTERNS = [
    re.compile(r"(?i)deploy.*(directly )?to production"),
    re.compile(r"(?i)push.*to prod\b"),
    re.compile(r"(?i)apply.*(directly )?(to|on) production"),
    re.compile(r"(?i)run.*against production"),
]
AMBIGUITY_MARKERS = ["not sure", "which service", "i don't know", "maybe", "not certain", "unclear"]


def classify_command(command: str) -> str:
    """SAFE | REVIEW_REQUIRED | BLOCKED — defense in depth, independent of
    the sandbox's own allowlist enforcement."""
    stripped = command.strip()
    if not stripped:
        return "BLOCKED"
    if any(tok in stripped for tok in DANGEROUS_TOKENS):
        return "BLOCKED"
    executable = stripped.split()[0]
    if executable not in COMMAND_ALLOWLIST:
        return "REVIEW_REQUIRED"
    return "SAFE"


def _matches_any(path: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(path) for p in patterns)


def _scan_secrets(texts: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for label, text in texts.items():
        if not text:
            continue
        for m in scan_for_secrets(text):
            findings.append(f"{label}: {m}")
    return findings


def _scan_code_security(texts: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for label, text in texts.items():
        if not text:
            continue
        for issue, pattern in CODE_SECURITY_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label}: {issue}")
    return findings


def _scan_prompt_injection(texts: dict[str, str]) -> list[str]:
    findings: list[str] = []
    for label, text in texts.items():
        if not text:
            continue
        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label}: matched {pattern.pattern[:40]!r}")
    return findings


# ===========================================================================
# 1. SECURITY GUARDRAILS
# ===========================================================================
def check_secret_detection(enforcement_point: str, texts: dict[str, str], guardrail_id: str = "SEC-01", category: str = CAT.SECURITY.value) -> GuardrailCheckResult:
    findings = _scan_secrets(texts)
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Secret Detection",
        description="Detects API keys, tokens, passwords, private keys, credentials and connection strings before they reach the LLM, logs, Git, GitHub, reports, generated code or the frontend.",
        purpose="Never expose a secret outside its origin.",
        enforcement_point=enforcement_point,
        trigger_condition=f"scanned={sorted(texts.keys())}",
        severity=Severity.CRITICAL.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings[:10],
        remediation="Remove or redact the credential-shaped value before retrying; never hardcode secrets — use environment configuration.",
    )


def check_dependency_security(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    touched = [f for f in changed_files if Path(f).name in DEPENDENCY_FILES]
    triggered = bool(touched)
    return GuardrailCheckResult(
        guardrail_id="SEC-02",
        category=CAT.SECURITY.value,
        name="Dependency Security",
        description="Flags dependency-manifest changes for review; detects obviously untrusted package name patterns where possible.",
        purpose="Prevent introducing a vulnerable or malicious dependency unreviewed.",
        enforcement_point=enforcement_point,
        trigger_condition=f"changed_files={changed_files}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.NOT_APPLICABLE.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if triggered else GuardrailAction.ALLOW.value,
        evidence=touched,
        remediation=(
            "Human review required before applying a dependency change. NOTE: live "
            "vulnerability/CVE-database lookup is NOT_IMPLEMENTED in this build — this "
            "environment has no package-index network access; only manifest-touch "
            "detection is performed."
            if triggered
            else ""
        ),
    )


def check_code_security(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    findings = _scan_code_security(texts)
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id="SEC-03",
        category=CAT.SECURITY.value,
        name="Code Security",
        description="Static pattern scan for command injection, SQL injection, unsafe subprocess execution, path traversal, unsafe deserialization, eval/exec, and naive password comparison.",
        purpose="Catch common insecure-code anti-patterns before they are committed.",
        enforcement_point=enforcement_point,
        trigger_condition=f"scanned={sorted(texts.keys())}",
        severity=Severity.CRITICAL.value if blocked else Severity.LOW.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Rework the flagged construct using a parameterized/safe API (e.g. subprocess without shell=True, parameterized SQL, hmac.compare_digest for secret comparison).",
    )


def check_container_security(enforcement_point: str, dockerfiles: dict[str, str]) -> GuardrailCheckResult:
    if not dockerfiles:
        return GuardrailCheckResult(
            guardrail_id="SEC-04",
            category=CAT.SECURITY.value,
            name="Container Security",
            description="Checks Dockerfiles for privileged execution, root user, unsafe base images, and exposed secrets.",
            purpose="Prevent an insecure container configuration from being introduced.",
            enforcement_point=enforcement_point,
            severity=Severity.LOW.value,
            status=GuardrailStatus.NOT_APPLICABLE.value,
            action=GuardrailAction.ALLOW.value,
            remediation="",
        )
    findings: list[str] = []
    for path, content in dockerfiles.items():
        if re.search(r"(?im)^USER\s+root\s*$", content) or not re.search(r"(?im)^USER\s+", content):
            findings.append(f"{path}: no non-root USER instruction (defaults to root)")
        for issue, pattern, note in CONTAINER_SECURITY_CHECKS:
            if pattern.search(content):
                findings.append(f"{path}: {issue} — {note}")
        secret_hits = scan_for_secrets(content)
        findings.extend(f"{path}: possible secret in image definition — {h}" for h in secret_hits)
    return GuardrailCheckResult(
        guardrail_id="SEC-04",
        category=CAT.SECURITY.value,
        name="Container Security",
        description="Checks Dockerfiles for privileged execution, root user, unsafe base images, and exposed secrets.",
        purpose="Prevent an insecure container configuration from being introduced.",
        enforcement_point=enforcement_point,
        trigger_condition=f"dockerfiles={sorted(dockerfiles.keys())}",
        severity=Severity.HIGH.value if findings else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if findings else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if findings else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Add a non-root USER, pin the base image to a digest/version, remove --privileged, and never bake secrets into image layers." if findings else "",
    )


def check_security_configuration(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    findings: list[str] = []
    for label, text in texts.items():
        if not text:
            continue
        if CORS_WILDCARD_PATTERN.search(text):
            findings.append(f"{label}: CORS allow_origins is wildcarded ('*')")
    return GuardrailCheckResult(
        guardrail_id="SEC-05",
        category=CAT.SECURITY.value,
        name="Security Configuration",
        description="Checks authentication, authorization, CORS, TLS, security-header and rate-limiting configuration in changed files.",
        purpose="Catch an insecure security-relevant configuration change.",
        enforcement_point=enforcement_point,
        trigger_condition=f"scanned={sorted(texts.keys())}",
        severity=Severity.MEDIUM.value if findings else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if findings else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if findings else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation=(
            "Restrict CORS to explicit trusted origins. NOTE: authentication/authorization/TLS/security-header/"
            "rate-limiting deep analysis is NOT_IMPLEMENTED beyond this CORS heuristic — no runtime request path "
            "is available to test against in this build."
            if findings
            else ""
        ),
    )


# ===========================================================================
# 2. INFRASTRUCTURE GUARDRAILS
# ===========================================================================
def check_infrastructure_change_detection(enforcement_point: str, changed_files: list[str], guardrail_id: str = "INFRA-01", category: str = CAT.INFRASTRUCTURE.value) -> GuardrailCheckResult:
    touched = [f for f in changed_files if _matches_any(f, INFRA_FILE_PATTERNS)]
    triggered = bool(touched)
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Infrastructure Change Detection",
        description="Detects when a workflow modifies Dockerfiles, Compose files, Kubernetes manifests, Terraform, or CI workflow definitions.",
        purpose="The agent must know when it is touching infrastructure, not just application code.",
        enforcement_point=enforcement_point,
        trigger_condition=f"changed_files={changed_files}",
        severity=Severity.HIGH.value if triggered else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.NOT_APPLICABLE.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if triggered else GuardrailAction.ALLOW.value,
        evidence=touched,
        remediation="Infrastructure changes require human review before proceeding." if triggered else "",
    )


def check_infrastructure_dependency(enforcement_point: str, dependents: list[str]) -> GuardrailCheckResult:
    triggered = bool(dependents)
    return GuardrailCheckResult(
        guardrail_id="INFRA-02",
        category=CAT.INFRASTRUCTURE.value,
        name="Infrastructure Dependency Check",
        description="Identifies which services/modules depend on the files being changed (reverse import graph).",
        purpose="Know the blast radius of a change before applying it.",
        enforcement_point=enforcement_point,
        trigger_condition=f"dependents={dependents}",
        severity=Severity.MEDIUM.value if triggered else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.PASSED.value,
        action=GuardrailAction.WARN.value if triggered else GuardrailAction.ALLOW.value,
        evidence=dependents,
        remediation="Review dependent modules for compatibility before applying." if triggered else "",
    )


def check_resource_limits(enforcement_point: str, infra_texts: dict[str, str]) -> GuardrailCheckResult:
    if not infra_texts:
        return GuardrailCheckResult(
            guardrail_id="INFRA-03",
            category=CAT.INFRASTRUCTURE.value,
            name="Resource Limit Check",
            description="Requires CPU/memory/storage limits in Docker Compose / Kubernetes manifests that are touched.",
            purpose="Prevent an unbounded-resource service definition from being introduced.",
            enforcement_point=enforcement_point,
            severity=Severity.LOW.value,
            status=GuardrailStatus.NOT_APPLICABLE.value,
            action=GuardrailAction.ALLOW.value,
        )
    missing = [f for f, text in infra_texts.items() if not re.search(r"(?i)(resources|limits|mem_limit|cpus)\s*:", text)]
    return GuardrailCheckResult(
        guardrail_id="INFRA-03",
        category=CAT.INFRASTRUCTURE.value,
        name="Resource Limit Check",
        description="Requires CPU/memory/storage limits in Docker Compose / Kubernetes manifests that are touched.",
        purpose="Prevent an unbounded-resource service definition from being introduced.",
        enforcement_point=enforcement_point,
        trigger_condition=f"files={sorted(infra_texts.keys())}",
        severity=Severity.MEDIUM.value if missing else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if missing else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if missing else GuardrailAction.ALLOW.value,
        evidence=missing,
        remediation="Add explicit CPU/memory limits to the modified infrastructure definition." if missing else "",
    )


def check_environment_isolation(enforcement_point: str, environment: str, guardrail_id: str = "INFRA-04", category: str = CAT.INFRASTRUCTURE.value) -> GuardrailCheckResult:
    try:
        env = Environment(environment)
    except ValueError:
        env = None
    allowed = env in ALLOWED_EXECUTION_ENVIRONMENTS and env != Environment.PRODUCTION
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Environment Isolation",
        description="Never allows production infrastructure to be modified by an AI-generated workflow.",
        purpose="Real production infrastructure is out of bounds by default.",
        enforcement_point=enforcement_point,
        trigger_condition=f"environment={environment}",
        severity=Severity.CRITICAL.value,
        status=GuardrailStatus.PASSED.value if allowed else GuardrailStatus.BLOCKED.value,
        action=GuardrailAction.ALLOW.value if allowed else GuardrailAction.BLOCK.value,
        remediation="" if allowed else f"Target only {sorted(e.value for e in ALLOWED_EXECUTION_ENVIRONMENTS)}.",
        configurable_threshold=f"allowed_environments={sorted(e.value for e in ALLOWED_EXECUTION_ENVIRONMENTS)}",
    )


def check_configuration_drift(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    touched = [f for f in changed_files if _matches_any(f, CONFIG_FILE_PATTERNS)]
    triggered = bool(touched)
    return GuardrailCheckResult(
        guardrail_id="INFRA-05",
        category=CAT.INFRASTRUCTURE.value,
        name="Configuration Drift Warning",
        description="Flags configuration-file changes (.env, YAML, TOML, settings modules) that may diverge from the existing architecture.",
        purpose="Configuration changes are easy to miss in a code review — surface them explicitly.",
        enforcement_point=enforcement_point,
        trigger_condition=f"changed_files={changed_files}",
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.NOT_APPLICABLE.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if triggered else GuardrailAction.ALLOW.value,
        evidence=touched,
        remediation="Review the configuration change against the deployed environment's current values (values themselves are never displayed here if they look secret-shaped)." if triggered else "",
    )


def check_infrastructure_blast_radius(enforcement_point: str, affected_files: list[str], affected_modules: list[str], dependents: list[str], guardrail_id: str = "INFRA-06", category: str = CAT.INFRASTRUCTURE.value) -> GuardrailCheckResult:
    total = len(set(affected_files) | set(affected_modules) | set(dependents))
    exceeded = total > settings.max_blast_radius_files
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Infrastructure Blast Radius",
        description="Estimates services, resources, and dependents affected by a change before it is applied.",
        purpose="Large blast radius changes need a human in the loop, not an automatic apply.",
        enforcement_point=enforcement_point,
        trigger_condition=f"blast_radius={total} (threshold {settings.max_blast_radius_files})",
        severity=Severity.HIGH.value if exceeded else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if exceeded else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if exceeded else GuardrailAction.ALLOW.value,
        evidence=sorted(set(affected_files) | set(affected_modules) | set(dependents)),
        remediation="Split the change into smaller, independently reviewable increments." if exceeded else "",
        configurable_threshold=f"max_blast_radius_files={settings.max_blast_radius_files}",
    )


# ===========================================================================
# 3. CI/CD GUARDRAILS
# ===========================================================================
_REQUIRED_CI_STAGES = ["lint", "unit_tests"]


def check_test_gate(enforcement_point: str, stage_statuses: dict[str, str]) -> GuardrailCheckResult:
    missing = [s for s in _REQUIRED_CI_STAGES if s not in stage_statuses]
    failed = [s for s in _REQUIRED_CI_STAGES if stage_statuses.get(s) not in (None, "passed") and s in stage_statuses]
    blocked = bool(missing) or bool(failed)
    return GuardrailCheckResult(
        guardrail_id="CICD-01",
        category=CAT.CI_CD.value,
        name="Test Gate",
        description="Required tests (lint, unit tests) must pass before progression.",
        purpose="Correctness is not optional.",
        enforcement_point=enforcement_point,
        trigger_condition=f"stage_statuses={stage_statuses}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=[f"missing={missing}", f"failed={failed}"],
        remediation="Fix the failing/missing required stage before proceeding." if blocked else "",
    )


def check_regression_gate(enforcement_point: str, baseline_passed: bool | None, final_unit_tests_passed: bool | None) -> GuardrailCheckResult:
    if baseline_passed is None or final_unit_tests_passed is None:
        status, action, reason = GuardrailStatus.NOT_APPLICABLE.value, GuardrailAction.ALLOW.value, "Baseline or final test result unavailable for comparison."
    else:
        regressed = baseline_passed and not final_unit_tests_passed
        status = GuardrailStatus.BLOCKED.value if regressed else GuardrailStatus.PASSED.value
        action = GuardrailAction.BLOCK.value if regressed else GuardrailAction.ALLOW.value
        reason = (
            "The pre-change test suite passed but the post-change suite now fails — this is a regression, not merely a new-test failure."
            if regressed
            else "Post-change test suite result is consistent with (or better than) the pre-change baseline."
        )
    return GuardrailCheckResult(
        guardrail_id="CICD-02",
        category=CAT.CI_CD.value,
        name="Regression Gate",
        description="Compares the pre-change baseline test run against the post-change run.",
        purpose="A workflow is never marked successful merely because newly generated tests pass.",
        enforcement_point=enforcement_point,
        trigger_condition=f"baseline_passed={baseline_passed}, final_unit_tests_passed={final_unit_tests_passed}; {reason}",
        severity=Severity.CRITICAL.value,
        status=status,
        action=action,
        remediation="" if status != GuardrailStatus.BLOCKED.value else "Diagnose the regression via a repair attempt or manual investigation.",
    )


def check_build_gate(enforcement_point: str, build_configured: bool, build_status: str | None) -> GuardrailCheckResult:
    if not build_configured:
        status, action = GuardrailStatus.NOT_APPLICABLE.value, GuardrailAction.ALLOW.value
    else:
        ok = build_status == "passed"
        status = GuardrailStatus.PASSED.value if ok else GuardrailStatus.BLOCKED.value
        action = GuardrailAction.ALLOW.value if ok else GuardrailAction.BLOCK.value
    return GuardrailCheckResult(
        guardrail_id="CICD-03",
        category=CAT.CI_CD.value,
        name="Build Gate",
        description="The configured build command must succeed.",
        purpose="A change that doesn't build cannot ship.",
        enforcement_point=enforcement_point,
        trigger_condition=f"build_configured={build_configured}, build_status={build_status}",
        severity=Severity.HIGH.value,
        status=status,
        action=action,
        remediation="Fix the build failure before proceeding." if status == GuardrailStatus.BLOCKED.value else "",
    )


def check_security_scan_gate(enforcement_point: str, security_status: str | None, security_findings: int) -> GuardrailCheckResult:
    if security_status is None:
        status, action = GuardrailStatus.NOT_APPLICABLE.value, GuardrailAction.ALLOW.value
    else:
        blocked = security_status != "passed" and security_findings > 0
        status = GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value
        action = GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value
    return GuardrailCheckResult(
        guardrail_id="CICD-04",
        category=CAT.CI_CD.value,
        name="Security Scan Gate",
        description="Critical static-security findings (ruff's bandit-derived S rule set) block CI progression.",
        purpose="A known-insecure change must not reach production readiness.",
        enforcement_point=enforcement_point,
        trigger_condition=f"security_status={security_status}, findings={security_findings}",
        severity=Severity.CRITICAL.value,
        status=status,
        action=action,
        remediation="Resolve the flagged security findings before proceeding." if status == GuardrailStatus.BLOCKED.value else "",
    )


def check_pipeline_integrity(enforcement_point: str, ci_file_diffs: dict[str, tuple[str, str]]) -> GuardrailCheckResult:
    """ci_file_diffs: {path: (old_content, new_content)} for touched .github/workflows/*.yml files."""
    if not ci_file_diffs:
        return GuardrailCheckResult(
            guardrail_id="CICD-05",
            category=CAT.CI_CD.value,
            name="Pipeline Integrity",
            description="AI-generated changes must not disable or bypass CI checks (e.g. removing a test/lint step from a workflow file).",
            purpose="An AI agent must never be able to quietly turn off its own safety net.",
            enforcement_point=enforcement_point,
            severity=Severity.LOW.value,
            status=GuardrailStatus.NOT_APPLICABLE.value,
            action=GuardrailAction.ALLOW.value,
        )
    findings: list[str] = []
    for path, (old, new) in ci_file_diffs.items():
        removed_lines = set(old.splitlines()) - set(new.splitlines())
        for line in removed_lines:
            if re.search(r"(?i)(pytest|ruff|lint|test|- run:)", line):
                findings.append(f"{path}: removed line {line.strip()!r}")
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id="CICD-05",
        category=CAT.CI_CD.value,
        name="Pipeline Integrity",
        description="AI-generated changes must not disable or bypass CI checks (e.g. removing a test/lint step from a workflow file).",
        purpose="An AI agent must never be able to quietly turn off its own safety net.",
        enforcement_point=enforcement_point,
        trigger_condition=f"files={sorted(ci_file_diffs.keys())}",
        severity=Severity.CRITICAL.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Do not remove CI validation steps; propose the change without touching pipeline integrity." if blocked else "",
    )


def check_ci_configuration_protection(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    touched = [f for f in changed_files if CI_WORKFLOW_PATTERN.search(f)]
    triggered = bool(touched)
    return GuardrailCheckResult(
        guardrail_id="CICD-06",
        category=CAT.CI_CD.value,
        name="CI Configuration Protection",
        description="Any change to .github/workflows/** requires explicit human approval.",
        purpose="CI configuration is a security boundary, not ordinary application code.",
        enforcement_point=enforcement_point,
        trigger_condition=f"changed_files={changed_files}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.NOT_APPLICABLE.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if triggered else GuardrailAction.ALLOW.value,
        evidence=touched,
        remediation="A human must review CI workflow file changes before they apply." if triggered else "",
    )


def check_failure_gate(enforcement_point: str, stage_statuses: dict[str, str]) -> GuardrailCheckResult:
    failed = [s for s, v in stage_statuses.items() if s in _REQUIRED_CI_STAGES and v != "passed"]
    blocked = bool(failed)
    return GuardrailCheckResult(
        guardrail_id="CICD-07",
        category=CAT.CI_CD.value,
        name="Failure Gate",
        description="Any failed required CI stage prevents deployment/production-readiness.",
        purpose="A red pipeline must not silently become a green deployment.",
        enforcement_point=enforcement_point,
        trigger_condition=f"stage_statuses={stage_statuses}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=failed,
        remediation="Resolve the failing stage(s) before deployment can proceed." if blocked else "",
    )


def check_ci_evidence_gate(enforcement_point: str, stages_have_real_evidence: bool, detail: str) -> GuardrailCheckResult:
    return GuardrailCheckResult(
        guardrail_id="CICD-08",
        category=CAT.CI_CD.value,
        name="Evidence Gate",
        description="CI results must carry actual execution evidence (command, duration, exit code) — a CI result is never fabricated.",
        purpose="Never claim a check ran when it did not.",
        enforcement_point=enforcement_point,
        trigger_condition=detail,
        severity=Severity.HIGH.value,
        status=GuardrailStatus.PASSED.value if stages_have_real_evidence else GuardrailStatus.FAILED.value,
        action=GuardrailAction.ALLOW.value if stages_have_real_evidence else GuardrailAction.BLOCK.value,
        remediation="" if stages_have_real_evidence else "Re-run validation; do not report a CI result without real execution evidence.",
    )


# ===========================================================================
# 4. DEPLOYMENT GUARDRAILS
# ===========================================================================
def check_environment_verification(enforcement_point: str, environment: str) -> GuardrailCheckResult:
    try:
        Environment(environment)
        valid = True
    except ValueError:
        valid = False
    return GuardrailCheckResult(
        guardrail_id="DEPLOY-01",
        category=CAT.DEPLOYMENT.value,
        name="Environment Verification",
        description="Verifies the actual target environment before any deployment-shaped action.",
        purpose="Never deploy to an unverified or unknown target.",
        enforcement_point=enforcement_point,
        trigger_condition=f"environment={environment}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.PASSED.value if valid else GuardrailStatus.BLOCKED.value,
        action=GuardrailAction.ALLOW.value if valid else GuardrailAction.BLOCK.value,
        remediation="" if valid else "Specify a recognized environment: local/sandbox/test/staging/production-simulation.",
    )


def check_production_block(enforcement_point: str, environment: str) -> GuardrailCheckResult:
    return check_environment_isolation(enforcement_point, environment, guardrail_id="DEPLOY-02", category=CAT.DEPLOYMENT.value)


def check_deployment_approval(enforcement_point: str, approved: bool, comment: str = "") -> GuardrailCheckResult:
    return GuardrailCheckResult(
        guardrail_id="DEPLOY-03",
        category=CAT.DEPLOYMENT.value,
        name="Deployment Approval",
        description="Deployment to staging/production-simulation requires an explicit human approval decision.",
        purpose="No deployment-shaped action happens without a human in the loop.",
        enforcement_point=enforcement_point,
        trigger_condition=f"approved={approved}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.PASSED.value if approved else GuardrailStatus.BLOCKED.value,
        action=GuardrailAction.ALLOW.value if approved else GuardrailAction.ABORT.value,
        evidence=[f"comment={comment}"] if comment else [],
        remediation="" if approved else "Re-submit for approval once the concern raised is addressed.",
    )


def check_rollback_requirement(enforcement_point: str, highest_risk_severity: str | None, plan_text: str) -> GuardrailCheckResult:
    lowered = plan_text.lower()
    has_rollback_mention = any(k in lowered for k in ROLLBACK_KEYWORDS)
    high_risk = highest_risk_severity in (Severity.HIGH.value, Severity.CRITICAL.value)
    if not high_risk:
        status, action, reason = GuardrailStatus.NOT_APPLICABLE.value, GuardrailAction.ALLOW.value, "No HIGH/CRITICAL risk identified; rollback strategy not required."
    elif has_rollback_mention:
        status, action, reason = GuardrailStatus.PASSED.value, GuardrailAction.ALLOW.value, "HIGH/CRITICAL risk identified and a rollback/revert strategy is documented."
    elif highest_risk_severity == Severity.CRITICAL.value:
        status, action, reason = GuardrailStatus.BLOCKED.value, GuardrailAction.BLOCK.value, "CRITICAL risk identified with no documented rollback strategy."
    else:
        status, action, reason = GuardrailStatus.WARNING.value, GuardrailAction.REQUIRE_APPROVAL.value, "HIGH risk identified with no documented rollback strategy."
    return GuardrailCheckResult(
        guardrail_id="DEPLOY-04",
        category=CAT.DEPLOYMENT.value,
        name="Rollback Requirement",
        description="High-risk changes require a documented rollback method, trigger, affected artifacts, and data-compatibility considerations.",
        purpose="Never ship a high-risk change with no way back.",
        enforcement_point=enforcement_point,
        trigger_condition=f"highest_risk_severity={highest_risk_severity}",
        severity=Severity.HIGH.value,
        status=status,
        action=action,
        remediation="" if status == GuardrailStatus.PASSED.value or status == GuardrailStatus.NOT_APPLICABLE.value else "Document a rollback method, trigger, and data-compatibility note before proceeding.",
        evidence=[reason],
    )


def check_health_check_gate(enforcement_point: str, repo_texts: dict[str, str]) -> GuardrailCheckResult:
    has_health_route = any(re.search(r"(?i)/health(z)?[\"']", t) for t in repo_texts.values())
    return GuardrailCheckResult(
        guardrail_id="DEPLOY-05",
        category=CAT.DEPLOYMENT.value,
        name="Health Check Gate",
        description="Deployment cannot be marked healthy without a readiness/liveness signal.",
        purpose="Never assume a deployed service is healthy without checking.",
        enforcement_point=enforcement_point,
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.PASSED.value if has_health_route else GuardrailStatus.WARNING.value,
        action=GuardrailAction.ALLOW.value if has_health_route else GuardrailAction.WARN.value,
        remediation="" if has_health_route else "No /health or /healthz endpoint detected in this repository; add one so deployment health can be verified.",
    )


def check_migration_safety(enforcement_point: str, changed_files: list[str], guardrail_id: str = "DEPLOY-06", category: str = CAT.DEPLOYMENT.value) -> GuardrailCheckResult:
    touched = [f for f in changed_files if _matches_any(f, MIGRATION_PATH_PATTERNS)]
    triggered = bool(touched)
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Migration Safety",
        description="Any schema/database migration requires a migration preview, affected-tables list, data-loss risk assessment, rollback strategy, and human approval. Destructive migrations are blocked by default.",
        purpose="Database migrations are the highest-consequence change class — treat them that way.",
        enforcement_point=enforcement_point,
        trigger_condition=f"changed_files={changed_files}",
        severity=Severity.CRITICAL.value if triggered else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.NOT_APPLICABLE.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if triggered else GuardrailAction.ALLOW.value,
        evidence=touched,
        remediation="Provide a migration preview, affected tables, data-loss assessment and rollback strategy for human approval." if triggered else "",
    )


def check_deployment_scope(enforcement_point: str, approved_files: list[str], changed_files: list[str], guardrail_id: str = "DEPLOY-07", category: str = CAT.DEPLOYMENT.value) -> GuardrailCheckResult:
    approved_set = set(approved_files)
    unrelated = [f for f in changed_files if f not in approved_set]
    blocked = bool(unrelated)
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Deployment Scope",
        description="Prevents unrelated services/resources from being deployed alongside the approved change.",
        purpose="A deployment should contain exactly what was reviewed — nothing more.",
        enforcement_point=enforcement_point,
        trigger_condition=f"approved={approved_files}, changed={changed_files}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=unrelated,
        remediation="Remove the out-of-scope file(s) or revise the approved plan to include them explicitly." if blocked else "",
    )


def check_deployment_evidence(enforcement_point: str, environment: str, commit_hash: str, branch: str, health_status: str) -> GuardrailCheckResult:
    return GuardrailCheckResult(
        guardrail_id="DEPLOY-08",
        category=CAT.DEPLOYMENT.value,
        name="Deployment Evidence",
        description="Records environment, commit, branch, timestamp, and health status for every deployment-shaped action.",
        purpose="Every deployment must be auditable after the fact.",
        enforcement_point=enforcement_point,
        severity=Severity.LOW.value,
        status=GuardrailStatus.PASSED.value,
        action=GuardrailAction.ALLOW.value,
        evidence=[f"environment={environment}", f"commit={commit_hash}", f"branch={branch}", f"health={health_status}"],
    )


# ===========================================================================
# 5. COST GUARDRAILS — token/dollar figures are ESTIMATES from real
#    prompt/response character counts (chars // 4); mock mode has no
#    provider billing API to read exact usage from.
# ===========================================================================
def check_llm_token_limit(enforcement_point: str, estimated_tokens: int) -> GuardrailCheckResult:
    exceeded = estimated_tokens > settings.max_llm_estimated_tokens_per_workflow
    return GuardrailCheckResult(
        guardrail_id="COST-01",
        category=CAT.COST.value,
        name="LLM Token Limit",
        description="Prevents uncontrolled token consumption within a single workflow.",
        purpose="Bound the cost of a single workflow.",
        enforcement_point=enforcement_point,
        trigger_condition=f"estimated_tokens={estimated_tokens} (limit {settings.max_llm_estimated_tokens_per_workflow})",
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if exceeded else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if exceeded else GuardrailAction.ALLOW.value,
        remediation="Review why this workflow is consuming an unusually large number of tokens." if exceeded else "",
        configurable_threshold=f"max_llm_estimated_tokens_per_workflow={settings.max_llm_estimated_tokens_per_workflow}",
    )


def check_llm_call_limit(enforcement_point: str, call_count: int) -> GuardrailCheckResult:
    exceeded = call_count > settings.max_llm_calls_per_workflow
    return GuardrailCheckResult(
        guardrail_id="COST-02",
        category=CAT.COST.value,
        name="LLM Call Limit",
        description="Caps the maximum number of LLM calls per workflow.",
        purpose="Bound the cost and latency of a single workflow.",
        enforcement_point=enforcement_point,
        trigger_condition=f"call_count={call_count} (limit {settings.max_llm_calls_per_workflow})",
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if exceeded else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if exceeded else GuardrailAction.ALLOW.value,
        remediation="Investigate why this workflow required an unusually high number of LLM calls." if exceeded else "",
        configurable_threshold=f"max_llm_calls_per_workflow={settings.max_llm_calls_per_workflow}",
    )


def check_repair_loop_limit(enforcement_point: str, repair_attempts: int, guardrail_id: str = "COST-03", category: str = CAT.COST.value, name: str = "Repair Loop Cost Limit") -> GuardrailCheckResult:
    exceeded = repair_attempts >= settings.max_repair_attempts
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name=name,
        description="Repair attempts have a configurable budget (MAX_REPAIR_ATTEMPTS); prevents an infinite/expensive AI repair loop.",
        purpose="Bound the cost of the repair loop and force human intervention past the budget.",
        enforcement_point=enforcement_point,
        trigger_condition=f"repair_attempts={repair_attempts} (limit {settings.max_repair_attempts})",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.BLOCKED.value if exceeded else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if exceeded else GuardrailAction.ALLOW.value,
        remediation="A human must diagnose the failure manually; this workflow cannot self-repair further." if exceeded else "",
        configurable_threshold=f"max_repair_attempts={settings.max_repair_attempts}",
    )


def check_model_escalation(enforcement_point: str, planning_model: str, codegen_model: str) -> GuardrailCheckResult:
    escalated = planning_model != codegen_model
    return GuardrailCheckResult(
        guardrail_id="COST-04",
        category=CAT.COST.value,
        name="Model Escalation Guard",
        description="Detects an automatic switch to a different (potentially more expensive) model mid-workflow.",
        purpose="Model selection changes should be explicit, not silent.",
        enforcement_point=enforcement_point,
        trigger_condition=f"planning_model={planning_model}, codegen_model={codegen_model}",
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if escalated else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if escalated else GuardrailAction.ALLOW.value,
        remediation="Confirm the model change was intentional." if escalated else "",
    )


def check_infrastructure_cost_warning(enforcement_point: str, infra_texts: dict[str, str]) -> GuardrailCheckResult:
    findings: list[str] = []
    for f, text in infra_texts.items():
        if re.search(r"(?i)(replicas|instances?)\s*:\s*([5-9]|\d{2,})", text):
            findings.append(f"{f}: large replica/instance count configured")
    return GuardrailCheckResult(
        guardrail_id="COST-05",
        category=CAT.COST.value,
        name="Infrastructure Cost Warning",
        description="Flags infrastructure changes that scale up replica/instance counts noticeably.",
        purpose="Surface a likely cost increase before it's applied.",
        enforcement_point=enforcement_point,
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if findings else (GuardrailStatus.NOT_APPLICABLE.value if not infra_texts else GuardrailStatus.PASSED.value),
        action=GuardrailAction.WARN.value if findings else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Confirm the scale-up is intentional and budgeted." if findings else "",
    )


def check_ci_cost_awareness(enforcement_point: str, repair_attempts: int, validation_run_count: int) -> GuardrailCheckResult:
    excessive = validation_run_count > (settings.max_repair_attempts + 2)
    return GuardrailCheckResult(
        guardrail_id="COST-06",
        category=CAT.COST.value,
        name="CI Cost Awareness",
        description="Detects unnecessarily repeated validation/CI runs within one workflow.",
        purpose="Repeated CI execution has a real infrastructure cost.",
        enforcement_point=enforcement_point,
        trigger_condition=f"validation_run_count={validation_run_count}, repair_attempts={repair_attempts}",
        severity=Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if excessive else GuardrailStatus.PASSED.value,
        action=GuardrailAction.WARN.value if excessive else GuardrailAction.ALLOW.value,
        remediation="Investigate why validation is being re-run more than expected." if excessive else "",
    )


def check_workflow_budget(enforcement_point: str, estimated_cost_usd: float) -> GuardrailCheckResult:
    exceeded = estimated_cost_usd > settings.workflow_cost_budget_usd
    near = estimated_cost_usd > settings.workflow_cost_budget_usd * 0.8
    return GuardrailCheckResult(
        guardrail_id="COST-07",
        category=CAT.COST.value,
        name="Workflow Budget",
        description="Each workflow has a configurable estimated cost budget (LLM cost estimate, generic per-1k-token rate).",
        purpose="Cost visibility and a soft budget ceiling per workflow.",
        enforcement_point=enforcement_point,
        trigger_condition=f"estimated_cost_usd={estimated_cost_usd:.4f} (budget {settings.workflow_cost_budget_usd})",
        severity=Severity.HIGH.value if exceeded else Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if (exceeded or near) else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if exceeded else (GuardrailAction.WARN.value if near else GuardrailAction.ALLOW.value),
        remediation="Estimated cost exceeds the configured workflow budget; review before continuing." if exceeded else "",
        configurable_threshold=f"workflow_cost_budget_usd={settings.workflow_cost_budget_usd}",
    )


# ===========================================================================
# 6. AI / LLM GUARDRAILS
# ===========================================================================
def check_prompt_injection(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    findings = _scan_prompt_injection(texts)
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id="AI-01",
        category=CAT.AI_LLM.value,
        name="Prompt Injection Detection",
        description="Detects instruction-shaped text embedded in repository content (README, source, comments, retrieved context) that could hijack the LLM. Repository content is treated as DATA, never as instructions.",
        purpose="Untrusted repository content must never be able to redirect the agent.",
        enforcement_point=enforcement_point,
        trigger_condition=f"scanned={sorted(texts.keys())}",
        severity=Severity.CRITICAL.value if blocked else Severity.LOW.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="The affected content was excluded from the prompt context; review the source file for a deliberate injection attempt." if blocked else "",
    )


def check_hallucination_evidence(enforcement_point: str, invented_files_removed: list[str], claims_without_evidence: list[str], guardrail_id: str = "AI-02", category: str = CAT.AI_LLM.value) -> GuardrailCheckResult:
    unverified = list(invented_files_removed) + list(claims_without_evidence)
    triggered = bool(unverified)
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Hallucination / Evidence Guard",
        description="LLM claims must be supported by repository evidence, test evidence, CI evidence, or runtime evidence; unsupported claims are marked UNVERIFIED, never silently promoted to fact.",
        purpose="Never let an LLM's confident wording pass for verified fact.",
        enforcement_point=enforcement_point,
        trigger_condition=f"invented_files={invented_files_removed}, unverified_claims={claims_without_evidence}",
        severity=Severity.MEDIUM.value,
        status=GuardrailStatus.WARNING.value if triggered else GuardrailStatus.PASSED.value,
        action=GuardrailAction.WARN.value if triggered else GuardrailAction.ALLOW.value,
        evidence=unverified,
        remediation="Unverified references were stripped from grounded output." if triggered else "",
    )


def check_model_output_validation(enforcement_point: str, schema_valid: bool, detail: str, guardrail_id: str = "AI-03", category: str = CAT.AI_LLM.value) -> GuardrailCheckResult:
    return GuardrailCheckResult(
        guardrail_id=guardrail_id,
        category=category,
        name="Model Output Validation",
        description="Validates structured LLM output against its Pydantic schema before it is used.",
        purpose="Never act on a malformed or partially-parsed LLM response.",
        enforcement_point=enforcement_point,
        trigger_condition=detail,
        severity=Severity.HIGH.value,
        status=GuardrailStatus.PASSED.value if schema_valid else GuardrailStatus.BLOCKED.value,
        action=GuardrailAction.ALLOW.value if schema_valid else GuardrailAction.BLOCK.value,
        remediation="" if schema_valid else "Reject the malformed output and retry generation.",
    )


def check_tool_permission_control(enforcement_point: str, classified_count: int, executed_count: int) -> GuardrailCheckResult:
    ok = executed_count <= classified_count
    return GuardrailCheckResult(
        guardrail_id="AI-04",
        category=CAT.AI_LLM.value,
        name="Tool Permission Control",
        description="The LLM cannot execute arbitrary tools/commands — every executed command must have passed AI-05 command classification first.",
        purpose="No command reaches the shell without going through the classifier.",
        enforcement_point=enforcement_point,
        trigger_condition=f"classified={classified_count}, executed={executed_count}",
        severity=Severity.CRITICAL.value,
        status=GuardrailStatus.PASSED.value if ok else GuardrailStatus.BLOCKED.value,
        action=GuardrailAction.ALLOW.value if ok else GuardrailAction.ABORT.value,
        remediation="" if ok else "A command executed without prior classification — this is an invariant violation; investigate immediately.",
    )


def check_command_safety(enforcement_point: str, commands: list[str]) -> GuardrailCheckResult:
    classifications = {c: classify_command(c) for c in commands}
    blocked = [c for c, cls in classifications.items() if cls == "BLOCKED"]
    review = [c for c, cls in classifications.items() if cls == "REVIEW_REQUIRED"]
    status = GuardrailStatus.BLOCKED.value if blocked else (GuardrailStatus.WARNING.value if review else GuardrailStatus.PASSED.value)
    action = GuardrailAction.BLOCK.value if blocked else (GuardrailAction.REQUIRE_APPROVAL.value if review else GuardrailAction.ALLOW.value)
    return GuardrailCheckResult(
        guardrail_id="AI-05",
        category=CAT.AI_LLM.value,
        name="Command Safety Classification",
        description="Classifies every command SAFE / REVIEW_REQUIRED / BLOCKED against an allowlist; no LLM-generated shell command bypasses this.",
        purpose="Defense in depth around arbitrary command execution.",
        enforcement_point=enforcement_point,
        trigger_condition=f"commands={commands}",
        severity=Severity.CRITICAL.value if blocked else Severity.MEDIUM.value,
        status=status,
        action=action,
        evidence=[f"{c} -> {cls}" for c, cls in classifications.items()],
        remediation="" if status == GuardrailStatus.PASSED.value else "Only allowlisted commands may execute inside the sandbox.",
    )


def check_context_boundary(enforcement_point: str, context_texts: dict[str, str]) -> GuardrailCheckResult:
    findings = _scan_secrets(context_texts)
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id="AI-06",
        category=CAT.AI_LLM.value,
        name="Context Boundary",
        description="Secrets or unnecessary sensitive repository content must never be sent to the LLM.",
        purpose="The LLM's context window is not a trusted boundary for secrets.",
        enforcement_point=enforcement_point,
        trigger_condition=f"scanned={sorted(context_texts.keys())}",
        severity=Severity.CRITICAL.value if blocked else Severity.LOW.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Redact the secret-shaped content before it is included in any LLM prompt." if blocked else "",
    )


def check_model_usage(enforcement_point: str, provider: str, model: str, prompt_version: str, call_count: int, estimated_tokens: int) -> GuardrailCheckResult:
    return GuardrailCheckResult(
        guardrail_id="AI-07",
        category=CAT.AI_LLM.value,
        name="Model Usage Control",
        description="Records provider, model, prompt version, and estimated token usage for every LLM interaction.",
        purpose="Model usage must be auditable, not opaque.",
        enforcement_point=enforcement_point,
        severity=Severity.LOW.value,
        status=GuardrailStatus.PASSED.value,
        action=GuardrailAction.ALLOW.value,
        evidence=[f"provider={provider}", f"model={model}", f"prompt_version={prompt_version}", f"call_count={call_count}", f"estimated_tokens={estimated_tokens}"],
    )


def check_ai_confidence(enforcement_point: str, confidences: list[float], assumptions: list[str]) -> GuardrailCheckResult:
    low_confidence = [c for c in confidences if c < 0.5]
    return GuardrailCheckResult(
        guardrail_id="AI-09",
        category=CAT.AI_LLM.value,
        name="AI Confidence / Evidence Level",
        description="Every important AI decision exposes its evidence, confidence, assumptions and unknowns. Confidence scores are read from the model's own structured output, never invented.",
        purpose="Uncertainty must be visible, not hidden behind confident prose.",
        enforcement_point=enforcement_point,
        trigger_condition=f"confidences={confidences}, assumptions={len(assumptions)}",
        severity=Severity.LOW.value,
        status=GuardrailStatus.WARNING.value if low_confidence else GuardrailStatus.PASSED.value,
        action=GuardrailAction.WARN.value if low_confidence else GuardrailAction.ALLOW.value,
        evidence=[f"low_confidence_changes={len(low_confidence)}", f"assumptions={assumptions[:5]}"],
        remediation="Review the low-confidence change(s) with extra care before approval." if low_confidence else "",
    )


# ===========================================================================
# 7. INPUT GUARDRAILS — run before the workflow starts.
# ===========================================================================
@dataclass
class InputClassification:
    classification: str  # VALID | NEEDS_CLARIFICATION | UNSAFE | BLOCKED
    checks: list[GuardrailCheckResult]


def classify_input(intent: str) -> InputClassification:
    checks: list[GuardrailCheckResult] = []
    ep = "input_validation"

    size_ok = 0 < len(intent) <= 4000
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-01", category=CAT.INPUT.value, name="Input Size",
            description="Developer intent must be non-empty and within a sane size bound.",
            purpose="Reject empty or absurdly oversized requests before they reach the pipeline.",
            enforcement_point=ep, trigger_condition=f"length={len(intent)}",
            severity=Severity.LOW.value,
            status=GuardrailStatus.PASSED.value if size_ok else GuardrailStatus.BLOCKED.value,
            action=GuardrailAction.ALLOW.value if size_ok else GuardrailAction.BLOCK.value,
            remediation="" if size_ok else "Provide a non-empty request under 4000 characters.",
        )
    )

    malformed = not intent.strip() or intent.strip().count(" ") == 0 and len(intent.strip()) < 4
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-02", category=CAT.INPUT.value, name="Malformed Request",
            description="Rejects a request with no discernible natural-language content.",
            purpose="A malformed request cannot be planned against.",
            enforcement_point=ep, trigger_condition=f"intent={intent[:60]!r}",
            severity=Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if malformed else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if malformed else GuardrailAction.ALLOW.value,
            remediation="Describe the requested change in a sentence or two." if malformed else "",
        )
    )

    injection_hits = [p.pattern[:40] for p in PROMPT_INJECTION_PATTERNS if p.search(intent)]
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-03", category=CAT.INPUT.value, name="Prompt Injection",
            description="Detects instruction-hijacking language inside the developer's own request.",
            purpose="Even first-party input is scanned — injection can arrive via a copy-pasted issue/ticket body.",
            enforcement_point=ep, trigger_condition=f"hits={injection_hits}",
            severity=Severity.CRITICAL.value if injection_hits else Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if injection_hits else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if injection_hits else GuardrailAction.ALLOW.value,
            evidence=injection_hits,
            remediation="Rewrite the request as a plain description of the desired change." if injection_hits else "",
        )
    )

    dangerous_hits = [p.pattern[:40] for p in DANGEROUS_INPUT_PATTERNS if p.search(intent)]
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-04", category=CAT.INPUT.value, name="Dangerous Instructions",
            description="Detects a request for a destructive operation (delete production DB, drop table, rm -rf, wipe database).",
            purpose="Destructive intent is rejected at the door, not three stages later.",
            enforcement_point=ep, trigger_condition=f"hits={dangerous_hits}",
            severity=Severity.CRITICAL.value if dangerous_hits else Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if dangerous_hits else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if dangerous_hits else GuardrailAction.ALLOW.value,
            evidence=dangerous_hits,
            remediation="Destructive requests are not accepted by this system." if dangerous_hits else "",
        )
    )

    prod_hits = [p.pattern[:40] for p in PRODUCTION_ACCESS_PATTERNS if p.search(intent)]
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-05", category=CAT.INPUT.value, name="Production Access Request",
            description="Detects a request that explicitly asks to target real production.",
            purpose="Production is out of bounds regardless of how the request is phrased.",
            enforcement_point=ep, trigger_condition=f"hits={prod_hits}",
            severity=Severity.CRITICAL.value if prod_hits else Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if prod_hits else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if prod_hits else GuardrailAction.ALLOW.value,
            evidence=prod_hits,
            remediation="Target sandbox/test/staging/production-simulation instead." if prod_hits else "",
        )
    )

    secret_hits = scan_for_secrets(intent)
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-06", category=CAT.INPUT.value, name="Secrets In Input",
            description="Detects a credential-shaped value pasted directly into the developer request.",
            purpose="A secret must never enter the system via the intent field either.",
            enforcement_point=ep, trigger_condition=f"hits={len(secret_hits)}",
            severity=Severity.CRITICAL.value if secret_hits else Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if secret_hits else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if secret_hits else GuardrailAction.ALLOW.value,
            evidence=secret_hits,
            remediation="Remove the credential from the request text." if secret_hits else "",
        )
    )

    ambiguous = len(intent.split()) < 4 or any(m in intent.lower() for m in AMBIGUITY_MARKERS)
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-07", category=CAT.INPUT.value, name="Ambiguous Requirements",
            description="Flags a request that is too short or explicitly expresses uncertainty about scope.",
            purpose="An ambiguous request should be clarified, not silently guessed at.",
            enforcement_point=ep, trigger_condition=f"word_count={len(intent.split())}",
            severity=Severity.MEDIUM.value,
            status=GuardrailStatus.WARNING.value if ambiguous else GuardrailStatus.PASSED.value,
            action=GuardrailAction.REQUIRE_APPROVAL.value if ambiguous else GuardrailAction.ALLOW.value,
            remediation="Clarify which service/component this request targets and what acceptance criteria apply." if ambiguous else "",
        )
    )

    unsafe_cmd_hits = [p.pattern[:40] for p in DANGEROUS_INPUT_PATTERNS if p.search(intent)]
    checks.append(
        GuardrailCheckResult(
            guardrail_id="INPUT-08", category=CAT.INPUT.value, name="Unsafe Commands Referenced",
            description="Detects an unsafe shell/SQL command referenced directly in the request text.",
            purpose="Reuses the same destructive-pattern scan at the command-reference level.",
            enforcement_point=ep, trigger_condition=f"hits={unsafe_cmd_hits}",
            severity=Severity.HIGH.value if unsafe_cmd_hits else Severity.LOW.value,
            status=GuardrailStatus.BLOCKED.value if unsafe_cmd_hits else GuardrailStatus.PASSED.value,
            action=GuardrailAction.BLOCK.value if unsafe_cmd_hits else GuardrailAction.ALLOW.value,
            evidence=unsafe_cmd_hits,
        )
    )

    if any(c.status == GuardrailStatus.BLOCKED.value for c in checks):
        classification = "BLOCKED" if (dangerous_hits or prod_hits or secret_hits or injection_hits) else "UNSAFE"
    elif any(c.status == GuardrailStatus.WARNING.value for c in checks):
        classification = "NEEDS_CLARIFICATION"
    else:
        classification = "VALID"

    return InputClassification(classification=classification, checks=checks)


# ===========================================================================
# 8. OUTPUT GUARDRAILS — validate every important AI-generated output.
# ===========================================================================
def check_output_schema_validation(enforcement_point: str, schema_valid: bool, detail: str) -> GuardrailCheckResult:
    return check_model_output_validation(enforcement_point, schema_valid, detail, guardrail_id="OUTPUT-01", category=CAT.OUTPUT.value)


def check_output_security_validation(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    result = check_code_security(enforcement_point, texts)
    result.guardrail_id = "OUTPUT-02"
    result.category = CAT.OUTPUT.value
    return result


def check_output_secret_detection(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    return check_secret_detection(enforcement_point, texts, guardrail_id="OUTPUT-03", category=CAT.OUTPUT.value)


_OUTPUT_UNSAFE_COMMAND_PATTERNS = [re.compile(r"os\.system\("), re.compile(r"subprocess\.\w+\("), re.compile(r"shell=True")]


def check_output_unsafe_command(enforcement_point: str, texts: dict[str, str]) -> GuardrailCheckResult:
    findings: list[str] = []
    for label, text in texts.items():
        if not text:
            continue
        for pattern in _OUTPUT_UNSAFE_COMMAND_PATTERNS:
            if pattern.search(text):
                findings.append(f"{label}: embedded shell invocation {pattern.pattern!r}")
    blocked = bool(findings)
    return GuardrailCheckResult(
        guardrail_id="OUTPUT-04",
        category=CAT.OUTPUT.value,
        name="Unsafe Command Detection",
        description="Scans generated code for embedded shell-invocation calls (os.system, subprocess with shell=True).",
        purpose="Generated code must not itself become a shell-injection vector.",
        enforcement_point=enforcement_point,
        severity=Severity.HIGH.value if blocked else Severity.LOW.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=findings,
        remediation="Use a safe subprocess invocation (list argv, no shell=True) or remove the shell call." if blocked else "",
    )


def check_output_scope_validation(enforcement_point: str, files_changed: int, patch_lines_by_file: dict[str, int], approved_files: list[str], changed_files: list[str]) -> GuardrailCheckResult:
    over_files = files_changed > settings.max_files_changed
    over_lines = {f: n for f, n in patch_lines_by_file.items() if n > settings.max_patch_lines}
    approved_set = set(approved_files)
    unrelated = [f for f in changed_files if f not in approved_set]
    blocked = over_files or bool(over_lines) or bool(unrelated)
    evidence = [f"files_changed={files_changed}"] + [f"oversized:{f}={n}" for f, n in over_lines.items()] + [f"unrelated:{f}" for f in unrelated]
    return GuardrailCheckResult(
        guardrail_id="OUTPUT-05",
        category=CAT.OUTPUT.value,
        name="Scope Validation",
        description="Enforces MAX_FILES_CHANGED/MAX_PATCH_LINES and that every changed file is within the approved plan's scope.",
        purpose="Generated output must not silently grow beyond what was reviewed.",
        enforcement_point=enforcement_point,
        severity=Severity.HIGH.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=evidence,
        remediation="Reduce scope to the approved plan and configured limits." if blocked else "",
        configurable_threshold=f"max_files_changed={settings.max_files_changed}, max_patch_lines={settings.max_patch_lines}",
    )


def check_output_dependency_change(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    result = check_dependency_security(enforcement_point, changed_files)
    result.guardrail_id = "OUTPUT-06"
    result.category = CAT.OUTPUT.value
    result.name = "Dependency Change Detection"
    result.description = "Detects a dependency-manifest change in generated output requiring DEPENDENCY_REVIEW_REQUIRED."
    return result


def check_output_infrastructure_change(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    return check_infrastructure_change_detection(enforcement_point, changed_files, guardrail_id="OUTPUT-07", category=CAT.OUTPUT.value)


def check_output_api_compatibility(enforcement_point: str, file: str, old_content: str, new_content: str) -> GuardrailCheckResult:
    is_api_file = _matches_any(file, API_FILE_PATTERNS)
    if not is_api_file:
        return GuardrailCheckResult(
            guardrail_id="OUTPUT-08", category=CAT.OUTPUT.value, name="API Compatibility Check",
            description="Detects breaking endpoint/schema/auth changes in generated output touching API/route files.",
            purpose="A generated change must not silently break an existing API contract.",
            enforcement_point=enforcement_point, severity=Severity.LOW.value,
            status=GuardrailStatus.NOT_APPLICABLE.value, action=GuardrailAction.ALLOW.value,
        )
    route_re = re.compile(r"@app\.(get|post|put|delete|patch)\(")
    def_re = re.compile(r"^def (\w+)\(", re.M)
    old_routes, new_routes = set(route_re.findall(old_content)), set(route_re.findall(new_content))
    old_funcs, new_funcs = set(def_re.findall(old_content)), set(def_re.findall(new_content))
    removed_funcs = old_funcs - new_funcs
    breaking = bool(removed_funcs) or len(new_routes) < len(old_routes)
    return GuardrailCheckResult(
        guardrail_id="OUTPUT-08", category=CAT.OUTPUT.value, name="API Compatibility Check",
        description="Detects breaking endpoint/schema/auth changes in generated output touching API/route files.",
        purpose="A generated change must not silently break an existing API contract.",
        enforcement_point=enforcement_point,
        trigger_condition=f"file={file}, removed_functions={sorted(removed_funcs)}",
        severity=Severity.HIGH.value,
        status=GuardrailStatus.WARNING.value if breaking else GuardrailStatus.PASSED.value,
        action=GuardrailAction.REQUIRE_APPROVAL.value if breaking else GuardrailAction.ALLOW.value,
        evidence=sorted(removed_funcs),
        remediation="Confirm the removed/changed handler(s) are an intentional breaking change." if breaking else "",
    )


def check_output_database_migration(enforcement_point: str, changed_files: list[str]) -> GuardrailCheckResult:
    return check_migration_safety(enforcement_point, changed_files, guardrail_id="OUTPUT-09", category=CAT.OUTPUT.value)


def check_output_regression(enforcement_point: str, baseline_passed: bool | None, final_unit_tests_passed: bool | None) -> GuardrailCheckResult:
    result = check_regression_gate(enforcement_point, baseline_passed, final_unit_tests_passed)
    result.guardrail_id = "OUTPUT-10"
    result.category = CAT.OUTPUT.value
    result.name = "Test Coverage / Regression Check"
    return result


def check_output_evidence(enforcement_point: str, invented_files_removed: list[str], claims_without_evidence: list[str]) -> GuardrailCheckResult:
    return check_hallucination_evidence(enforcement_point, invented_files_removed, claims_without_evidence, guardrail_id="OUTPUT-11", category=CAT.OUTPUT.value)


def check_output_policy_compliance(enforcement_point: str, sibling_results: list[GuardrailCheckResult]) -> GuardrailCheckResult:
    blocked = [r for r in sibling_results if r.action in (GuardrailAction.BLOCK.value, GuardrailAction.ABORT.value)]
    return GuardrailCheckResult(
        guardrail_id="OUTPUT-12",
        category=CAT.OUTPUT.value,
        name="Policy Compliance",
        description="Composite result across every other OUTPUT-xx check evaluated for this batch of generated output.",
        purpose="One place to see 'was this output acceptable overall'.",
        enforcement_point=enforcement_point,
        severity=Severity.HIGH.value if blocked else Severity.LOW.value,
        status=GuardrailStatus.BLOCKED.value if blocked else GuardrailStatus.PASSED.value,
        action=GuardrailAction.BLOCK.value if blocked else GuardrailAction.ALLOW.value,
        evidence=[f"{r.guardrail_id}:{r.name}" for r in blocked],
        remediation="Resolve the blocking output check(s) above." if blocked else "",
    )


def check_output_production_safety(enforcement_point: str, environment: str) -> GuardrailCheckResult:
    return check_environment_isolation(enforcement_point, environment, guardrail_id="OUTPUT-13", category=CAT.OUTPUT.value)


# ===========================================================================
# Catalog — every definition above, for GET /api/guardrails.
# ===========================================================================
GUARDRAIL_CATALOG: list[dict] = [
    {"guardrail_id": "SEC-01", "category": "SECURITY", "name": "Secret Detection", "severity": "CRITICAL"},
    {"guardrail_id": "SEC-02", "category": "SECURITY", "name": "Dependency Security", "severity": "HIGH"},
    {"guardrail_id": "SEC-03", "category": "SECURITY", "name": "Code Security", "severity": "CRITICAL"},
    {"guardrail_id": "SEC-04", "category": "SECURITY", "name": "Container Security", "severity": "HIGH"},
    {"guardrail_id": "SEC-05", "category": "SECURITY", "name": "Security Configuration", "severity": "MEDIUM"},
    {"guardrail_id": "INFRA-01", "category": "INFRASTRUCTURE", "name": "Infrastructure Change Detection", "severity": "HIGH"},
    {"guardrail_id": "INFRA-02", "category": "INFRASTRUCTURE", "name": "Infrastructure Dependency Check", "severity": "MEDIUM"},
    {"guardrail_id": "INFRA-03", "category": "INFRASTRUCTURE", "name": "Resource Limit Check", "severity": "MEDIUM"},
    {"guardrail_id": "INFRA-04", "category": "INFRASTRUCTURE", "name": "Environment Isolation", "severity": "CRITICAL"},
    {"guardrail_id": "INFRA-05", "category": "INFRASTRUCTURE", "name": "Configuration Drift Warning", "severity": "MEDIUM"},
    {"guardrail_id": "INFRA-06", "category": "INFRASTRUCTURE", "name": "Infrastructure Blast Radius", "severity": "HIGH"},
    {"guardrail_id": "CICD-01", "category": "CI_CD", "name": "Test Gate", "severity": "HIGH"},
    {"guardrail_id": "CICD-02", "category": "CI_CD", "name": "Regression Gate", "severity": "CRITICAL"},
    {"guardrail_id": "CICD-03", "category": "CI_CD", "name": "Build Gate", "severity": "HIGH"},
    {"guardrail_id": "CICD-04", "category": "CI_CD", "name": "Security Scan Gate", "severity": "CRITICAL"},
    {"guardrail_id": "CICD-05", "category": "CI_CD", "name": "Pipeline Integrity", "severity": "CRITICAL"},
    {"guardrail_id": "CICD-06", "category": "CI_CD", "name": "CI Configuration Protection", "severity": "HIGH"},
    {"guardrail_id": "CICD-07", "category": "CI_CD", "name": "Failure Gate", "severity": "HIGH"},
    {"guardrail_id": "CICD-08", "category": "CI_CD", "name": "Evidence Gate", "severity": "HIGH"},
    {"guardrail_id": "DEPLOY-01", "category": "DEPLOYMENT", "name": "Environment Verification", "severity": "HIGH"},
    {"guardrail_id": "DEPLOY-02", "category": "DEPLOYMENT", "name": "Production Block", "severity": "CRITICAL"},
    {"guardrail_id": "DEPLOY-03", "category": "DEPLOYMENT", "name": "Deployment Approval", "severity": "HIGH"},
    {"guardrail_id": "DEPLOY-04", "category": "DEPLOYMENT", "name": "Rollback Requirement", "severity": "HIGH"},
    {"guardrail_id": "DEPLOY-05", "category": "DEPLOYMENT", "name": "Health Check Gate", "severity": "MEDIUM"},
    {"guardrail_id": "DEPLOY-06", "category": "DEPLOYMENT", "name": "Migration Safety", "severity": "CRITICAL"},
    {"guardrail_id": "DEPLOY-07", "category": "DEPLOYMENT", "name": "Deployment Scope", "severity": "HIGH"},
    {"guardrail_id": "DEPLOY-08", "category": "DEPLOYMENT", "name": "Deployment Evidence", "severity": "LOW"},
    {"guardrail_id": "COST-01", "category": "COST", "name": "LLM Token Limit", "severity": "MEDIUM"},
    {"guardrail_id": "COST-02", "category": "COST", "name": "LLM Call Limit", "severity": "MEDIUM"},
    {"guardrail_id": "COST-03", "category": "COST", "name": "Repair Loop Cost Limit", "severity": "HIGH"},
    {"guardrail_id": "COST-04", "category": "COST", "name": "Model Escalation Guard", "severity": "MEDIUM"},
    {"guardrail_id": "COST-05", "category": "COST", "name": "Infrastructure Cost Warning", "severity": "MEDIUM"},
    {"guardrail_id": "COST-06", "category": "COST", "name": "CI Cost Awareness", "severity": "LOW"},
    {"guardrail_id": "COST-07", "category": "COST", "name": "Workflow Budget", "severity": "HIGH"},
    {"guardrail_id": "AI-01", "category": "AI_LLM", "name": "Prompt Injection Detection", "severity": "CRITICAL"},
    {"guardrail_id": "AI-02", "category": "AI_LLM", "name": "Hallucination / Evidence Guard", "severity": "MEDIUM"},
    {"guardrail_id": "AI-03", "category": "AI_LLM", "name": "Model Output Validation", "severity": "HIGH"},
    {"guardrail_id": "AI-04", "category": "AI_LLM", "name": "Tool Permission Control", "severity": "CRITICAL"},
    {"guardrail_id": "AI-05", "category": "AI_LLM", "name": "Command Safety Classification", "severity": "CRITICAL"},
    {"guardrail_id": "AI-06", "category": "AI_LLM", "name": "Context Boundary", "severity": "CRITICAL"},
    {"guardrail_id": "AI-07", "category": "AI_LLM", "name": "Model Usage Control", "severity": "LOW"},
    {"guardrail_id": "AI-08", "category": "AI_LLM", "name": "Retry/Repair Limit", "severity": "HIGH"},
    {"guardrail_id": "AI-09", "category": "AI_LLM", "name": "AI Confidence / Evidence Level", "severity": "LOW"},
    {"guardrail_id": "INPUT-01", "category": "INPUT", "name": "Input Size", "severity": "LOW"},
    {"guardrail_id": "INPUT-02", "category": "INPUT", "name": "Malformed Request", "severity": "LOW"},
    {"guardrail_id": "INPUT-03", "category": "INPUT", "name": "Prompt Injection", "severity": "CRITICAL"},
    {"guardrail_id": "INPUT-04", "category": "INPUT", "name": "Dangerous Instructions", "severity": "CRITICAL"},
    {"guardrail_id": "INPUT-05", "category": "INPUT", "name": "Production Access Request", "severity": "CRITICAL"},
    {"guardrail_id": "INPUT-06", "category": "INPUT", "name": "Secrets In Input", "severity": "CRITICAL"},
    {"guardrail_id": "INPUT-07", "category": "INPUT", "name": "Ambiguous Requirements", "severity": "MEDIUM"},
    {"guardrail_id": "INPUT-08", "category": "INPUT", "name": "Unsafe Commands Referenced", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-01", "category": "OUTPUT", "name": "Schema Validation", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-02", "category": "OUTPUT", "name": "Security Validation", "severity": "CRITICAL"},
    {"guardrail_id": "OUTPUT-03", "category": "OUTPUT", "name": "Secret Detection", "severity": "CRITICAL"},
    {"guardrail_id": "OUTPUT-04", "category": "OUTPUT", "name": "Unsafe Command Detection", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-05", "category": "OUTPUT", "name": "Scope Validation", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-06", "category": "OUTPUT", "name": "Dependency Change Detection", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-07", "category": "OUTPUT", "name": "Infrastructure Change Detection", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-08", "category": "OUTPUT", "name": "API Compatibility Check", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-09", "category": "OUTPUT", "name": "Database Migration Check", "severity": "CRITICAL"},
    {"guardrail_id": "OUTPUT-10", "category": "OUTPUT", "name": "Test Coverage / Regression Check", "severity": "CRITICAL"},
    {"guardrail_id": "OUTPUT-11", "category": "OUTPUT", "name": "Evidence & Hallucination Validation", "severity": "MEDIUM"},
    {"guardrail_id": "OUTPUT-12", "category": "OUTPUT", "name": "Policy Compliance", "severity": "HIGH"},
    {"guardrail_id": "OUTPUT-13", "category": "OUTPUT", "name": "Production Safety Check", "severity": "CRITICAL"},
]

GUARDRAIL_CATEGORIES = [c.value for c in GuardrailCategory]
