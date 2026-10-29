"""Production verification (validation stages prod_*).

Unit tests prove the code; these stages prove the *running service*. The app
is started the way it ships — its Docker image with production resource
limits when a Docker engine is available, otherwise the same uvicorn command
its Dockerfile runs (no --reload) — and tested over real HTTP:

  prod_boot        starts and becomes healthy within the boot timeout
  prod_smoke       every read endpoint answers without a server error
  prod_api         write endpoints: valid input accepted, invalid input
                   rejected with 4xx, create -> read -> update -> delete
  prod_robustness  malformed, oversized and hostile input never causes a 5xx
                   or a leaked stack trace, and the service stays healthy
  prod_load        concurrent traffic: no errors, p95 latency within budget
  prod_recovery    stops cleanly, restarts and is healthy again

Nothing here reaches outside this machine: the app listens on 127.0.0.1
only, runs with secrets removed from its environment, and is always stopped
afterwards. Endpoints are discovered from the app's OpenAPI schema, and
request bodies are generated from it, so no test data is hard-coded per app.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from app.core.config import settings
from app.services.validation.sandbox import CommandResult

STAGES = ("prod_boot", "prod_smoke", "prod_api", "prod_robustness", "prod_load", "prod_recovery")
STAGE_TITLES = {
    "prod_boot": "Boot",
    "prod_smoke": "Smoke test",
    "prod_api": "API contract",
    "prod_robustness": "Hostile input",
    "prod_load": "Load test",
    "prod_recovery": "Restart & recovery",
}

_SECRET_ENV = re.compile(r"(?i)(token|secret|key|password|credential)")
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)|File \"[^\"]+\.py\", line \d+")
_SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
_MAX_ROUTES = 8  # per stage, so a large API can't make validation run for ever


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Route:
    method: str
    path: str
    body: dict | None = None
    params: list[dict] = field(default_factory=list)

    @property
    def has_path_params(self) -> bool:
        return "{" in self.path


# ---------------------------------------------------------------------------
# Running the app
# ---------------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RunningApp:
    """The app under test, as a container (image given) or a uvicorn process."""

    def __init__(
        self, workspace: Path, entry: str, container_port: int, health_path: str, image: str = "", instance: str = ""
    ) -> None:
        self.workspace = workspace
        self.entry = entry
        self.container_port = container_port
        self.health_path = health_path or "/"
        self.image = image
        self.port = _free_port()
        self.process: subprocess.Popen | None = None
        self.container = ""
        logs = Path(settings.workspaces_dir).parent / "prod-logs"
        logs.mkdir(parents=True, exist_ok=True)
        # Several copies of one release can run side by side (live + standby).
        self.name = f"{workspace.name}-{instance}" if instance else workspace.name
        self.log_path = logs / f"{self.name}.log"  # outside the workspace, so it is never committed
        self.log_path.write_text("", encoding="utf-8")

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def describe(self) -> str:
        if self.image:
            return f"docker run {self.image} (512 MB, 1 CPU, no capabilities) on 127.0.0.1:{self.port}"
        return f"uvicorn {self.entry} --host 127.0.0.1 --port {self.port} (production mode, no reload)"

    def start(self) -> None:
        if self.image:
            docker = shutil.which("docker") or "docker"
            self.container = "i2d-prod-" + re.sub(r"[^a-z0-9-]+", "-", self.name.lower())[-40:].strip("-")
            subprocess.run([docker, "rm", "-f", self.container], capture_output=True, timeout=60)  # noqa: S603
            run = subprocess.run(  # noqa: S603 - fixed argv
                [docker, "run", "-d", "--name", self.container, "-p", f"127.0.0.1:{self.port}:{self.container_port}",
                 "--memory", "512m", "--cpus", "1", "--pids-limit", "256", "--cap-drop", "ALL",
                 "--security-opt", "no-new-privileges", "-e", "ENV=production", self.image],
                capture_output=True, text=True, timeout=120,
            )
            if run.returncode != 0:
                raise RuntimeError(f"Could not start the container: {run.stderr.strip()[-500:]}")
            return
        env = {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}
        env.update(PYTHONPATH=str(self.workspace), ENV="production", APP_ENV="production",
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        with open(self.log_path, "a", encoding="utf-8") as log:
            self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
                [sys.executable, "-m", "uvicorn", self.entry, "--host", "127.0.0.1", "--port", str(self.port),
                 "--no-access-log"],
                cwd=self.workspace, env=env, stdout=log, stderr=subprocess.STDOUT,
            )

    def alive(self) -> bool:
        if self.container:
            docker = shutil.which("docker") or "docker"
            out = subprocess.run(  # noqa: S603
                [docker, "inspect", "-f", "{{.State.Running}}", self.container], capture_output=True, text=True, timeout=30
            )
            return out.stdout.strip() == "true"
        return self.process is not None and self.process.poll() is None

    def wait_healthy(self, timeout: float) -> float | None:
        """Seconds until the health endpoint answers < 400, or None."""
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            if not self.alive():
                return None
            try:
                if httpx.get(self.base_url + self.health_path, timeout=2).status_code < 400:
                    return time.monotonic() - started
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        return None

    def healthy(self) -> bool:
        try:
            return self.alive() and httpx.get(self.base_url + self.health_path, timeout=3).status_code < 400
        except httpx.HTTPError:
            return False

    def stop(self) -> float:
        """Stop the app; returns the seconds it took."""
        started = time.monotonic()
        if self.container:
            docker = shutil.which("docker") or "docker"
            subprocess.run([docker, "stop", "-t", "10", self.container], capture_output=True, timeout=60)  # noqa: S603
        elif self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        return time.monotonic() - started

    def remove(self) -> None:
        self.stop()
        if self.container:
            docker = shutil.which("docker") or "docker"
            subprocess.run([docker, "rm", "-f", self.container], capture_output=True, timeout=60)  # noqa: S603

    def port_released(self, timeout: float = 5.0) -> bool:
        """Whether the port can be bound again (the OS frees it just after exit)."""
        deadline = time.monotonic() + timeout
        while True:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", self.port))
                    return True
                except OSError:
                    pass
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)

    def logs(self, lines: int = 25) -> list[str]:
        if self.container:
            docker = shutil.which("docker") or "docker"
            out = subprocess.run(  # noqa: S603
                [docker, "logs", "--tail", str(lines), self.container], capture_output=True, text=True, timeout=30
            )
            return (out.stdout + out.stderr).splitlines()[-lines:]
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        except OSError:
            return []


# ---------------------------------------------------------------------------
# OpenAPI: routes and request bodies generated from their schemas
# ---------------------------------------------------------------------------
def routes_from_openapi(schema: dict) -> list[Route]:
    routes = []
    for path, ops in (schema.get("paths") or {}).items():
        if path in _SKIP_PATHS:
            continue
        for method, op in ops.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            content = (op.get("requestBody") or {}).get("content") or {}
            body = (content.get("application/json") or {}).get("schema")
            routes.append(Route(method.upper(), path, body, [p for p in op.get("parameters", []) if isinstance(p, dict)]))
    return routes


def _resolve(schema: dict, root: dict) -> dict:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 20:
        node: object = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        schema, seen = node if isinstance(node, dict) else {}, seen + 1
    return schema if isinstance(schema, dict) else {}


def sample_value(schema: dict, root: dict, name: str = "", depth: int = 0):  # noqa: ANN201 - any JSON value
    """A valid example value for a JSON schema (as FastAPI/Pydantic emit them)."""
    schema = _resolve(schema, root)
    if depth > 6:
        return None
    if schema.get("default") is not None:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if _resolve(o, root).get("type") != "null"] or schema[key]
            return sample_value(options[0], root, name, depth + 1)
    if "allOf" in schema:
        merged: dict = {}
        for part in schema["allOf"]:
            merged.update(_resolve(part, root))
        return sample_value(merged, root, name, depth + 1)
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        return {k: sample_value(v, root, k, depth + 1) for k, v in (schema.get("properties") or {}).items()}
    if kind == "array":
        count = min(max(1, int(schema.get("minItems", 1))), 3)
        return [sample_value(schema.get("items") or {}, root, name, depth + 1) for _ in range(count)]
    if kind in ("integer", "number"):
        low = schema.get("minimum", schema.get("exclusiveMinimum", 0) + 1 if "exclusiveMinimum" in schema else 1)
        high = schema.get("maximum", schema.get("exclusiveMaximum", low + 10) - 1 if "exclusiveMaximum" in schema else None)
        value = low if high is None else min(low, high)
        return int(value) if kind == "integer" else float(value)
    if kind == "boolean":
        return True
    return _sample_string(schema, name)


def _sample_string(schema: dict, name: str) -> str:
    fmt, lname = schema.get("format", ""), name.lower()
    by_format = {"date": "2030-01-15", "date-time": "2030-01-15T10:00:00Z", "uuid": "123e4567-e89b-12d3-a456-426614174000",
                 "email": "qa.user@example.com", "uri": "https://example.com", "url": "https://example.com"}
    if fmt in by_format:
        return by_format[fmt]
    candidates = []
    if "email" in lname:
        candidates.append("qa.user@example.com")
    if lname.endswith("url"):
        candidates.append("https://example.com")
    if "password" in lname:
        candidates.append("Str0ng-Passw0rd!")
    if "phone" in lname or "mobile" in lname:
        candidates += ["+15550100100", "9876543210"]
    value = f"Sample {name}".strip() if name else "Sample value"
    value = value.ljust(int(schema.get("minLength", 0)), "x")
    if schema.get("maxLength"):
        value = value[: int(schema["maxLength"])]
    candidates.append(value)
    if schema.get("pattern"):
        # Constrained strings: the first likely value that satisfies the pattern.
        candidates += ["9876543210", "+15550100100", "Sample", "sample", "ABC123", "123456", "560001", "A1", "SAMPLE"]
        return next((c for c in candidates if _matches(schema["pattern"], c)), candidates[0])
    return candidates[0]


def _matches(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def _fill_path(path: str, value: object = 1) -> str:
    return re.sub(r"\{[^}]+\}", str(value), path)


def _query(route: Route, root: dict) -> dict:
    return {
        p["name"]: sample_value(p.get("schema") or {}, root, p["name"])
        for p in route.params
        if p.get("in") == "query" and p.get("required")
    }


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------
def _result(app_label: str, checks: list[Check], started: float, notes: list[str] | None = None) -> CommandResult:
    ok = all(c.ok for c in checks)
    lines = [f"{'PASS' if c.ok else 'FAIL'}  {c.name}" + (f" — {c.detail}" if c.detail else "") for c in checks]
    if notes:
        lines += ["", "Notes:"] + [f"  · {n}" for n in notes]
    return CommandResult(command=app_label, exit_code=0 if ok else 1, stdout="\n".join(lines), stderr="",
                         duration_ms=int((time.monotonic() - started) * 1000))


def _skipped(reason: str) -> CommandResult:
    return CommandResult(command="production verification", exit_code=None, stdout=f"Skipped: {reason}", stderr="",
                         duration_ms=0, skipped=True)


def _no_leak(resp: httpx.Response) -> bool:
    return not _TRACEBACK.search(resp.text[:20000])


def _status_check(name: str, resp: httpx.Response | Exception, ok: Callable[[int], bool]) -> Check:
    if isinstance(resp, Exception):
        return Check(name, False, f"no response ({type(resp).__name__}: {str(resp)[:120]})")
    detail = f"HTTP {resp.status_code}"
    if not _no_leak(resp):
        return Check(name, False, detail + ", response leaks a Python stack trace")
    return Check(name, ok(resp.status_code), detail)


def _send(client: httpx.Client, method: str, url: str, **kw) -> httpx.Response | Exception:
    try:
        return client.request(method, url, **kw)
    except httpx.HTTPError as exc:
        return exc


@dataclass
class _Context:
    app: RunningApp
    client: httpx.Client
    openapi: dict
    routes: list[Route]
    kept_record: tuple[str, object] | None = None  # (item path, id) left behind to see if data survives a restart
    read_only: bool = False  # a release about to take real traffic: never create data in it


def _smoke(ctx: _Context) -> tuple[list[Check], list[str]]:
    checks = [_status_check(f"GET {ctx.app.health_path} (health)", _send(ctx.client, "GET", ctx.app.health_path),
                            lambda s: s < 400)]
    page = _send(ctx.client, "GET", "/")
    checks.append(_status_check("GET / (landing page)", page, lambda s: s < 500))
    gets = [r for r in ctx.routes if r.method == "GET" and not r.has_path_params and r.path not in ("/", ctx.app.health_path)]
    for route in gets[:_MAX_ROUTES]:
        started = time.monotonic()
        resp = _send(ctx.client, "GET", route.path, params=_query(route, ctx.openapi))
        check = _status_check(f"GET {route.path}", resp, lambda s: s < 500)
        elapsed = (time.monotonic() - started) * 1000
        check.detail += f", {elapsed:.0f} ms"
        if check.ok and elapsed > settings.prod_p95_budget_ms * 2:
            check.ok, check.detail = False, check.detail + " (too slow for a single request)"
        checks.append(check)
    notes = []
    if not ctx.openapi:
        notes.append("No OpenAPI schema at /openapi.json, so only / and the health endpoint were checked.")
    if not isinstance(page, Exception) and page.status_code < 400 and "text/html" in page.headers.get("content-type", ""):
        missing = [h for h in ("x-content-type-options", "content-security-policy") if h not in page.headers]
        if missing:
            notes.append(f"Consider adding security headers to pages: {', '.join(missing)}.")
    return checks, notes


def _api(ctx: _Context) -> tuple[list[Check], list[str]]:
    checks: list[Check] = []
    notes: list[str] = []
    writes = [r for r in ctx.routes if r.method in ("POST", "PUT", "PATCH") and r.body is not None and not r.has_path_params]
    if not writes:
        return [Check("API has no JSON write endpoints to verify", True)], notes
    for route in writes[:_MAX_ROUTES]:
        body = sample_value(route.body, ctx.openapi)
        resp = _send(ctx.client, route.method, route.path, json=body)
        if isinstance(resp, Exception) or resp.status_code >= 500 or not _no_leak(resp):
            checks.append(_status_check(f"{route.method} {route.path} with a valid body", resp, lambda s: s < 500))
            continue
        if resp.status_code >= 400:
            # The app may legitimately refuse generated data (e.g. it refers to
            # something that doesn't exist); what matters is a clean 4xx.
            checks.append(Check(f"{route.method} {route.path} with a valid body", True,
                                f"HTTP {resp.status_code} (refused cleanly: {resp.text[:100]!r})"))
        else:
            checks.append(Check(f"{route.method} {route.path} with a valid body", True, f"HTTP {resp.status_code}"))
            _round_trip(ctx, route, body, resp, checks, notes)
        required = _resolve(route.body, ctx.openapi).get("required")
        if required:
            bad = _send(ctx.client, route.method, route.path, json={})
            checks.append(_status_check(f"{route.method} {route.path} without required fields ({', '.join(required)})",
                                        bad, lambda s: 400 <= s < 500))
            wrong = _send(ctx.client, route.method, route.path, json={k: {"unexpected": ["type"]} for k in required})
            checks.append(_status_check(f"{route.method} {route.path} with wrong field types", wrong,
                                        lambda s: 400 <= s < 500))
    return checks, notes


def _round_trip(ctx: _Context, create: Route, body: object, resp: httpx.Response, checks: list[Check], notes: list[str]) -> None:
    """create -> read -> update -> delete -> read (404), when the API has item routes."""
    try:
        created = resp.json()
    except ValueError:
        return
    if not isinstance(created, dict) or "id" not in created:
        return
    item = next((r.path for r in ctx.routes if r.method == "GET" and re.fullmatch(re.escape(create.path) + r"/\{[^}/]+\}", r.path)), None)
    if item is None:
        return
    url = _fill_path(item, created["id"])
    read = _send(ctx.client, "GET", url)
    checks.append(_status_check(f"GET {item} returns the created record", read, lambda s: s == 200))
    if any(r.method == "PUT" and r.path == item for r in ctx.routes):
        checks.append(_status_check(f"PUT {item} updates it", _send(ctx.client, "PUT", url, json=body), lambda s: s < 300))
    if any(r.method == "DELETE" and r.path == item for r in ctx.routes):
        checks.append(_status_check(f"DELETE {item} removes it", _send(ctx.client, "DELETE", url), lambda s: s < 300))
        checks.append(_status_check(f"GET {item} after delete is 404", _send(ctx.client, "GET", url), lambda s: s == 404))
        again = _send(ctx.client, create.method, create.path, json=body)
        if not isinstance(again, Exception) and again.status_code < 300:
            try:
                ctx.kept_record = (item, again.json()["id"])
            except (ValueError, KeyError, TypeError):
                pass
    checks.append(_status_check(f"GET {_fill_path(item, 987654321)} (unknown id) is 404",
                                _send(ctx.client, "GET", _fill_path(item, 987654321)), lambda s: s in (404, 422)))


def _robustness(ctx: _Context) -> tuple[list[Check], list[str]]:
    no_5xx = lambda s: s < 500  # noqa: E731
    checks = [
        _status_check("GET an unknown route is 404", _send(ctx.client, "GET", "/__i2d_does_not_exist__"), lambda s: s == 404),
        _status_check("8 KB query string", _send(ctx.client, "GET", "/", params={"q": "x" * 8000}), no_5xx),
    ]
    traversal = _send(ctx.client, "GET", "/static/..%2f..%2fapp%2fmain.py")
    leaked = not isinstance(traversal, Exception) and traversal.status_code == 200 and "import" in traversal.text
    checks.append(Check("Path traversal through /static is refused", not leaked,
                        "source code was served" if leaked else ("no response" if isinstance(traversal, Exception) else f"HTTP {traversal.status_code}")))
    writes = [r for r in ctx.routes if r.method in ("POST", "PUT", "PATCH") and r.body is not None][:_MAX_ROUTES]
    nested: object = "x"
    for _ in range(200):
        nested = [nested]
    for route in writes:
        url = _fill_path(route.path)
        label = f"{route.method} {route.path}"
        checks.append(_status_check(f"{label}: malformed JSON", _send(ctx.client, route.method, url, content=b"{not json",
                                                                      headers={"content-type": "application/json"}),
                                    lambda s: 400 <= s < 500))
        if ctx.read_only:
            continue  # the remaining probes could be accepted and store data
        checks += [
            _status_check(f"{label}: array instead of object", _send(ctx.client, route.method, url, json=[]), no_5xx),
            _status_check(f"{label}: 1 MB payload", _send(ctx.client, route.method, url, json={"name": "x" * 1_000_000}), no_5xx),
            _status_check(f"{label}: deeply nested JSON", _send(ctx.client, route.method, url, json={"name": nested}), no_5xx),
            _status_check(f"{label}: script/SQL injection strings",
                          _send(ctx.client, route.method, url, json={"name": "<script>alert(1)</script>' OR '1'='1"}), no_5xx),
        ]
    for route in [r for r in ctx.routes if r.has_path_params and r.method == "GET"][:_MAX_ROUTES]:
        checks.append(_status_check(f"GET {route.path} with an invalid id", _send(ctx.client, "GET", _fill_path(route.path, "not-an-id%00")),
                                    lambda s: 400 <= s < 500))
    checks.append(Check("Service is still healthy afterwards", ctx.app.healthy()))
    return checks, []


def _load(ctx: _Context) -> tuple[list[Check], list[str]]:
    targets = [ctx.app.health_path] + [
        r.path for r in ctx.routes if r.method == "GET" and not r.has_path_params and not _query(r, ctx.openapi)
        and r.path != ctx.app.health_path
    ][:4]
    total, workers = settings.prod_load_requests, settings.prod_load_concurrency
    latencies: list[float] = []
    errors: list[str] = []

    def one(i: int) -> None:
        path = targets[i % len(targets)]
        started = time.monotonic()
        try:
            resp = ctx.client.get(path)
            if resp.status_code >= 500:
                errors.append(f"{path}: HTTP {resp.status_code}")
        except httpx.HTTPError as exc:
            errors.append(f"{path}: {type(exc).__name__}")
        latencies.append((time.monotonic() - started) * 1000)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, range(total)))
    elapsed = time.monotonic() - started
    ordered = sorted(latencies)

    def pct(p: float) -> float:
        return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]

    p95 = pct(95)
    checks = [
        Check(f"{total} requests, {workers} concurrent: no errors", not errors,
              f"{len(errors)} error(s): {', '.join(sorted(set(errors))[:3])}" if errors else "0 errors"),
        Check(f"p95 latency within {settings.prod_p95_budget_ms} ms", p95 <= settings.prod_p95_budget_ms, f"p95 {p95:.0f} ms"),
        Check("Service is still healthy afterwards", ctx.app.healthy()),
    ]
    notes = [
        f"Throughput {total / elapsed:.0f} req/s · p50 {statistics.median(ordered):.0f} ms · p95 {p95:.0f} ms · "
        f"p99 {pct(99):.0f} ms · max {ordered[-1]:.0f} ms",
        f"Endpoints: {', '.join(targets)}",
    ]
    return checks, notes


def _recovery(ctx: _Context) -> tuple[list[Check], list[str]]:
    app = ctx.app
    stop_seconds = app.stop()
    checks = [
        Check("Stops within 10 s", stop_seconds <= 11, f"{stop_seconds:.1f} s"),
        Check("Releases its port", app.port_released()),
    ]
    app.start()
    boot = app.wait_healthy(settings.prod_boot_timeout_seconds)
    checks.append(Check("Restarts and is healthy again", boot is not None, f"{boot:.1f} s" if boot is not None else "did not become healthy"))
    notes = []
    if boot is not None and ctx.kept_record:
        item, record_id = ctx.kept_record
        survived = _send(ctx.client, "GET", _fill_path(item, record_id))
        if not isinstance(survived, Exception):
            notes.append("Data survived the restart." if survived.status_code == 200 else
                         "Data did not survive the restart (in-memory storage): use a database before real users rely on it.")
    return checks, notes


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
RELEASE_STAGES = ("prod_smoke", "prod_robustness", "prod_load")


def verify_release(app: RunningApp) -> list[tuple[str, CommandResult]]:
    """Pre-release checks for a candidate that is running but not yet taking
    traffic. Read-only: nothing is created in an app that real users are about
    to use (the full write/round-trip checks ran during validation)."""
    results: list[tuple[str, CommandResult]] = []
    label = app.describe()
    with httpx.Client(base_url=app.base_url, timeout=10, limits=httpx.Limits(max_connections=settings.prod_load_concurrency)) as client:
        ctx = _Context(app, client, _openapi(client), [], read_only=True)
        ctx.routes = routes_from_openapi(ctx.openapi)
        for stage, step in (("prod_smoke", _smoke), ("prod_robustness", _robustness), ("prod_load", _load)):
            t0 = time.monotonic()
            if not app.healthy():
                checks, notes = [Check("Service is running", False, "it stopped responding")], []
            else:
                checks, notes = step(ctx)
            result = _result(label, checks, t0, notes)
            if result.exit_code:
                result.stderr = "\n".join(app.logs())
            results.append((stage, result))
    return results


def _openapi(client: httpx.Client) -> dict:
    try:
        resp = client.get("/openapi.json")
        if resp.status_code == 200:
            return resp.json()
    except (httpx.HTTPError, ValueError):
        pass
    return {}


def run(workspace: Path, image: str = "", skip_reason: str = "") -> list[tuple[str, CommandResult]]:
    """Run every production stage against `workspace` (or its built `image`)."""
    if skip_reason:
        return [(s, _skipped(skip_reason)) for s in STAGES]
    from app.services import containerize

    spec = containerize.detect(containerize.read_project_files(workspace))
    if spec is None:
        return [(s, _skipped("No runnable service was detected (no web app entry point).")) for s in STAGES]
    if not image and spec.kind != "python-asgi":
        return [(s, _skipped(f"A {spec.kind} app can only be started from its Docker image, and Docker isn't running here. "
                              "CI runs it from the image on GitHub.")) for s in STAGES]

    app = RunningApp(workspace, spec.entry, spec.port, spec.health_path, image)
    label = app.describe()
    results: list[tuple[str, CommandResult]] = []
    started = time.monotonic()
    try:
        app.start()
        boot = app.wait_healthy(settings.prod_boot_timeout_seconds)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        boot, error = None, str(exc)
    else:
        error = ""
    if boot is None:
        detail = error or ("the process exited" if not app.alive() else f"no healthy response within {settings.prod_boot_timeout_seconds} s")
        result = _result(label, [Check(f"Starts and answers {app.health_path}", False, detail)], started)
        result.stderr = "\n".join(app.logs())
        app.remove()
        return [("prod_boot", result)] + [(s, _skipped("The app did not start, so it could not be tested.")) for s in STAGES[1:]]
    results.append(("prod_boot", _result(label, [Check(f"Starts and answers {app.health_path}", True, f"healthy in {boot:.1f} s")],
                                         started, [f"Started as: {label}"])))

    try:
        with httpx.Client(base_url=app.base_url, timeout=10, limits=httpx.Limits(max_connections=settings.prod_load_concurrency)) as client:
            openapi = _openapi(client)
            ctx = _Context(app, client, openapi, routes_from_openapi(openapi))
            for stage, step in (("prod_smoke", _smoke), ("prod_api", _api), ("prod_robustness", _robustness),
                                ("prod_load", _load), ("prod_recovery", _recovery)):
                if not app.healthy():
                    down = _result(label, [Check("Service is running", False, "it stopped responding")], time.monotonic())
                    down.stderr = "\n".join(app.logs())
                    results.append((stage, down))
                    continue
                t0 = time.monotonic()
                checks, notes = step(ctx)
                result = _result(label, checks, t0, notes)
                if result.exit_code:
                    result.stderr = "\n".join(app.logs())
                results.append((stage, result))
    finally:
        app.remove()
    return results
