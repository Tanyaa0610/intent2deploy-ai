"""Before planning a fix for a problem reported on staging, check what the
code on staging already does.

A report like "create the backend as well" may ask for something the project
already has. Each capability the request mentions is looked for in the
repository with concrete evidence (routes, pages, files). If everything that
was asked for is already there, the person gets that answer immediately —
with the evidence — instead of a fix workflow that can only end in "no
changes". Anything not recognised or not found goes on to a real fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist", "build"}
_ROUTE = re.compile(r"""@\w+\.(get|post|put|patch|delete)\(\s*["']([^"']+)["']""")


@dataclass
class Finding:
    capability: str
    present: bool
    evidence: list[str] = field(default_factory=list)


@dataclass
class CheckResult:
    findings: list[Finding]
    unrecognised: bool  # the request asks for something this check can't evaluate

    @property
    def already_satisfied(self) -> bool:
        return bool(self.findings) and not self.unrecognised and all(f.present for f in self.findings)

    def summary(self) -> str:
        lines = []
        for f in self.findings:
            mark = "✅ already there" if f.present else "❌ missing"
            lines.append(f"{f.capability}: {mark}" + (f" — {'; '.join(f.evidence[:4])}" if f.evidence else ""))
        return "\n".join(lines)


def _files(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in root.rglob("*"):
        if not p.is_file() or any(part in _SKIP for part in p.relative_to(root).parts):
            continue
        if p.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".toml", ".yml", ".yaml",
                                    ".txt", ".md", ".cfg", ".ini"} and p.name != "Dockerfile":
            continue
        try:
            out[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            continue
        if len(out) > 400:
            break
    return out


def _routes(files: dict[str, str]) -> list[str]:
    routes = []
    for path, text in files.items():
        if path.endswith(".py") and not path.startswith("tests/"):
            routes += [f"{m.upper()} {p}" for m, p in _ROUTE.findall(text)]
    return routes


def _grep(files: dict[str, str], pattern: str, exts: tuple[str, ...] = ()) -> list[str]:
    rx = re.compile(pattern, re.I)
    return [p for p, t in files.items() if (not exts or p.endswith(exts)) and rx.search(t)]


# capability -> (words in the request that ask for it, how to find it in the code)
def _check_backend(files: dict[str, str]) -> Finding:
    routes = _routes(files)
    servers = _grep(files, r"FastAPI\(|Flask\(|express\(\)|createServer\(", (".py", ".js", ".ts"))
    api_routes = [r for r in routes if " /api/" in r or r.endswith(("/health",))]
    evidence = [f"server in {', '.join(servers[:2])}"] if servers else []
    if api_routes:
        evidence.append("endpoints: " + ", ".join(api_routes[:8]) + (" …" if len(api_routes) > 8 else ""))
    return Finding("Backend (server + API)", bool(servers and routes), evidence)


def _check_frontend(files: dict[str, str]) -> Finding:
    pages = [p for p in files if p.endswith(".html")] + [p for p in files if p.endswith((".tsx", ".jsx"))][:3]
    scripts = [p for p in files if p.endswith(".js") and "static" in p]
    return Finding("Frontend (pages the user interacts with)", bool(pages),
                   [f"pages: {', '.join(pages[:4])}"] + ([f"scripts: {', '.join(scripts[:3])}"] if scripts else []))


def _check_connected(files: dict[str, str]) -> Finding:
    """The pages call the backend's own API endpoints."""
    served = [r.split(" ", 1)[1] for r in _routes(files)]
    called: set[str] = set()
    for path, text in files.items():
        if path.endswith((".js", ".ts", ".tsx", ".jsx", ".html")) and not path.startswith(("tests/", ".github/")):
            called |= set(re.findall(r"""["'`](/api/[\w/.-]*\w)""", text))
    prefixes = [s.split("{")[0].rstrip("/") for s in served if "{" in s]
    matched = sorted(c for c in called if c in served or any(c.startswith(p) for p in prefixes))
    return Finding("Frontend connected to the backend", bool(matched),
                   [f"the pages call {', '.join(matched[:6])}" + (" …" if len(matched) > 6 else ""),
                    "each one is served by the backend"] if matched else [])


def _check_password_reset(files: dict[str, str]) -> Finding:
    routes = [r for r in _routes(files) if re.search(r"reset|forgot", r, re.I)]
    ui = _grep(files, r"forgot password|reset your password|reset-request", (".html", ".js", ".tsx", ".jsx"))
    return Finding("Password reset", bool(routes and ui),
                   ([f"endpoints: {', '.join(routes)}"] if routes else []) + ([f"screens in {', '.join(ui[:2])}"] if ui else []))


def _check_login(files: dict[str, str]) -> Finding:
    routes = [r for r in _routes(files) if re.search(r"login|signin|sign-in|register|signup", r, re.I)]
    return Finding("Sign in / create account", bool(routes), [f"endpoints: {', '.join(routes)}"] if routes else [])


def _check_database(files: dict[str, str]) -> Finding:
    hits = _grep(files, r"\bsqlite3\b|sqlalchemy|sqlmodel|psycopg|pymongo|create_engine\(", (".py", ".js", ".ts", ".txt"))
    return Finding("Database (data kept after a restart)", bool(hits), [f"used in {', '.join(hits[:3])}"] if hits else [])


def _check_tests(files: dict[str, str]) -> Finding:
    tests = [p for p in files if re.search(r"(^|/)tests?/|test_[^/]+\.py$|\.test\.[jt]sx?$", p)]
    return Finding("Automated tests", bool(tests), [f"{len(tests)} test file(s)"] if tests else [])


def _check_docker(files: dict[str, str]) -> Finding:
    return Finding("Docker", "Dockerfile" in files, ["Dockerfile"] if "Dockerfile" in files else [])


def _check_ci(files: dict[str, str]) -> Finding:
    wf = [p for p in files if p.startswith(".github/workflows/")]
    return Finding("CI pipeline", bool(wf), wf[:3])


def _check_dark_mode(files: dict[str, str]) -> Finding:
    hits = _grep(files, r"prefers-color-scheme:\s*dark|data-theme", (".css", ".html", ".js"))
    return Finding("Dark mode", bool(hits), hits[:2])


def _check_search(files: dict[str, str]) -> Finding:
    hits = _grep(files, r'type="search"|placeholder="search', (".html", ".js", ".tsx", ".jsx"))
    return Finding("Search", bool(hits), hits[:2])


def _check_responsive(files: dict[str, str]) -> Finding:
    hits = _grep(files, r"@media\s*\(max-width", (".css",))
    return Finding("Mobile-friendly layout", bool(hits), hits[:2])


CAPABILITIES = [
    (r"\b(back-?end|server|api|endpoints?)\b", _check_backend),
    (r"\b(front-?end|ui|user interface|web ?page)\b", _check_frontend),
    (r"\b(connect\w*|integrat\w*|link\w*|wire[ds]?|wiring|hook\w*( up)?|talks? to|call\w* the (api|back-?end))\b",
     _check_connected),
    (r"\b(password reset|reset (the )?password|forgot(ten)? password|reset (button|option|link|page))\b", _check_password_reset),
    (r"\b(log ?in|sign ?in|sign ?up|register|registration)\b", _check_login),
    (r"\b(database|db|persist\w*|sqlite|postgres\w*|mysql|mongo\w*|data is lost|save data)\b", _check_database),
    (r"\b(tests?|unit tests?|test cases?)\b", _check_tests),
    (r"\b(docker\w*|container\w*)\b", _check_docker),
    (r"\b(ci|ci/cd|pipeline|github actions)\b", _check_ci),
    (r"\b(dark ?mode|dark theme)\b", _check_dark_mode),
    (r"\b(search\w*)\b", _check_search),
    (r"\b(responsive|mobile)\b", _check_responsive),
]
# Words that just frame the request ("create the backend as well with frontend now").
_FILLER = re.compile(
    r"\b(please|pls|plz|also|as well|too|now|add|create|make|build|implement|include|with|and|the|a|an|it|its|of|for|to|"
    r"there|is|are|no|not|any|option|should|be|have|has|need|needs|want|wants|working|work|proper|properly|full|"
    r"complete|missing|button|link|page|feature|in|on|this|that|my|our|me|i|we|you|can|could|would|will|do|does|"
    r"don't|doesnt|isn't|isnt|show|shows|showing|one|both|just|only|well|same|thing|things|part|side|really)\b",
    re.I,
)


def check(repo_root: Path, problem: str) -> CheckResult:
    files = _files(repo_root)
    findings: list[Finding] = []
    remaining = problem.lower()
    for pattern, fn in CAPABILITIES:
        if re.search(pattern, problem, re.I):
            finding = fn(files)
            if finding.capability not in {f.capability for f in findings}:
                findings.append(finding)
            remaining = re.sub(pattern, " ", remaining, flags=re.I)
    leftover = [w for w in re.findall(r"[a-z]{3,}", _FILLER.sub(" ", remaining))]
    # A report about behaviour ("the button does nothing", "error when ...") is not a
    # capability that can be found in the code: it always goes on to a real fix.
    behaviour = re.search(r"\b(error|bug|broken|crash\w*|fail\w*|wrong|does nothing|doesn'?t work|not working|slow)\b",
                          problem, re.I)
    return CheckResult(findings, unrecognised=bool(leftover) or bool(behaviour))
