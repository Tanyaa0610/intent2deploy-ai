"""Zero-downtime deployments of a branch (normally staging) on this machine.

Each project keeps one stable address (its own port in PORT_RANGE). Behind it
a small traffic router forwards requests to the release that is live:

* Blue-green releases — a new version starts *next to* the live one on a
  private port and must pass read-only production checks (smoke, hostile
  input, load) before the router switches traffic to it. A release that
  fails is never switched to: the current version keeps serving and an alert
  is raised.
* Hot standby — a second copy of the live release runs idle. If the live copy
  stops answering, the router moves traffic to the standby on the very next
  request (no downtime) and a fresh standby is started.
* Watchdog — every few seconds the live release is health-checked through the
  public address. After repeated failures it heals: standby takeover, then
  rollback to the previous release (kept warm for a while after each
  release), then a restart. Every incident raises an alert.

Releases run either from their Docker image (when a Docker engine is
available) or with the fixed command `python -m uvicorn <entry>` — never a
command taken from the repository. Everything binds to 127.0.0.1, tokens and
keys from this server's environment are not passed on, and deployments are
tracked in memory: they stop when this server stops.
"""
from __future__ import annotations

import logging
import re
import shutil
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import uvicorn
from git import GitCommandError, Repo
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from app.core.config import settings
from app.services.validation.production import RunningApp

PORT_RANGE = range(8100, 8200)
log = logging.getLogger("intent2deploy.deployments")

_HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
                "transfer-encoding", "upgrade", "content-length", "content-encoding", "host"}
_MAINTENANCE_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="5">
<title>Back in a moment</title><style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;
min-height:90vh;color:#374151}div{text-align:center}</style></head><body><div><h1>We'll be right back</h1>
<p>The site is restarting. This page refreshes automatically.</p></div></body></html>"""


class PreviewError(Exception):
    """User-facing error."""


def preferred_port(key: str) -> int:
    """Each project gets its own stable port in PORT_RANGE (derived from its name)."""
    import zlib

    return PORT_RANGE.start + zlib.crc32(key.encode("utf-8")) % len(PORT_RANGE)


def _free_port(key: str = "") -> int:
    used = {d.port for d in _DEPLOYMENTS.values()}
    start = preferred_port(key) if key else PORT_RANGE.start
    # Try the project's own port first, then the next free one (wrapping around).
    ordered = [p for p in PORT_RANGE if p >= start] + [p for p in PORT_RANGE if p < start]
    for port in ordered:
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise PreviewError(f"No free port between {PORT_RANGE.start} and {PORT_RANGE.stop - 1}.")


def _previews_root() -> Path:
    return Path(settings.workspaces_dir).parent / "previews"


def _slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", key)


def _alert(severity: str, title: str, detail: str, key: str) -> None:
    from app.services import alerts

    alerts.raise_alert(severity, "release" if "release" in title.lower() else "monitor", title, detail, deployment=key)


# ---------------------------------------------------------------------------
# Traffic router: the stable public address
# ---------------------------------------------------------------------------
class Router:
    """Forwards every request on the public port to the live instance, and to
    the standby instead (promoting it) when the live one can't be reached."""

    def __init__(self, key: str, port: int, on_failure) -> None:  # noqa: ANN001 - callback(instance, promoted)
        self.key, self.port = key, port
        self.live: RunningApp | None = None
        self.standby: RunningApp | None = None
        self.release_sha = ""
        self.stats = {"requests": 0, "failovers": 0, "server_errors": 0, "unavailable": 0}
        self._lock = threading.Lock()
        self._on_failure = on_failure
        self._client: httpx.AsyncClient | None = None
        methods = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
        app = Starlette(routes=[Route("/{path:path}", self._proxy, methods=methods)], lifespan=self._lifespan)
        self._server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                                     access_log=False, lifespan="on"))
        self._thread = threading.Thread(target=self._server.run, daemon=True, name=f"router-{key}")

    def start(self, timeout: float = 15) -> None:
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise PreviewError(f"Could not open port {self.port} for {self.key}.")
            time.sleep(0.05)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() and self._server.started

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)

    def switch(self, live: RunningApp | None, standby: RunningApp | None, sha: str | None = None) -> None:
        with self._lock:
            self.live, self.standby = live, standby
            if sha is not None:
                self.release_sha = sha

    def _targets(self) -> list[RunningApp]:
        with self._lock:
            return [a for a in (self.live, self.standby) if a is not None]

    def _failed(self, instance: RunningApp) -> None:
        promoted = False
        with self._lock:
            if instance is self.live and self.standby is not None:
                self.live, self.standby = self.standby, None
                self.stats["failovers"] += 1
                promoted = True
        # Healing (alert, replacement standby) happens off the request path.
        threading.Thread(target=self._on_failure, args=(instance, promoted), daemon=True).start()

    @asynccontextmanager
    async def _lifespan(self, _app):  # noqa: ANN202
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=2), follow_redirects=False)
        yield
        await self._client.aclose()

    async def _proxy(self, request: Request) -> Response:
        body = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS}
        headers["x-forwarded-for"] = request.client.host if request.client else ""
        headers["x-forwarded-host"] = request.headers.get("host", "")
        tail = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        # A connection that was refused never reached the app, so any request
        # can be retried on the standby; other transport errors only for
        # requests that change nothing.
        safe = request.method in ("GET", "HEAD", "OPTIONS")
        self.stats["requests"] += 1
        for instance in self._targets():
            try:
                upstream = await self._client.request(request.method, instance.base_url + tail, headers=headers, content=body)
            except httpx.ConnectError:
                self._failed(instance)
                continue
            except httpx.TransportError:
                if safe:
                    self._failed(instance)
                    continue
                return Response("The app did not finish answering this request.", status_code=502)
            if upstream.status_code >= 500:
                self.stats["server_errors"] += 1
            response = Response(upstream.content, status_code=upstream.status_code)
            response.raw_headers = [
                (k.encode("latin-1"), v.encode("latin-1"))
                for k, v in upstream.headers.multi_items() if k.lower() not in _HOP_HEADERS
            ] + [(b"content-length", str(len(upstream.content)).encode()), (b"x-release", self.release_sha[:8].encode())]
            return response
        self.stats["unavailable"] += 1
        return HTMLResponse(_MAINTENANCE_PAGE, status_code=503, headers={"Retry-After": "5"})


# ---------------------------------------------------------------------------
# Releases and deployments
# ---------------------------------------------------------------------------
@dataclass
class Release:
    number: int
    branch: str
    sha: str
    folder: Path
    entry: str
    container_port: int
    health_path: str
    image: str = ""
    status: str = "candidate"  # candidate | live | previous | blocked | retired
    created_at: float = field(default_factory=time.time)
    checks: list[dict] = field(default_factory=list)
    reason: str = ""

    def launch(self, instance: str) -> RunningApp:
        app = RunningApp(self.folder, self.entry, self.container_port, self.health_path, self.image, instance=instance)
        app.start()
        return app

    def summary(self) -> dict:
        return {"number": self.number, "branch": self.branch, "sha": self.sha[:8], "status": self.status,
                "created_at": self.created_at, "checks": self.checks, "reason": self.reason}


class Deployment:
    def __init__(self, key: str, port: int) -> None:
        self.key, self.port = key, port
        self.router = Router(key, port, self._upstream_failed)
        self.releases: list[Release] = []
        self.live: Release | None = None
        self.previous: Release | None = None
        self.previous_app: RunningApp | None = None  # previous release kept warm for instant rollback
        self.previous_until = 0.0
        self.lock = threading.RLock()
        self.started_at = time.time()
        self.open_path = "/"
        self.last_boot_log = ""  # why the last instance failed to start
        self._instances = 0
        self.monitor = {"checks": 0, "ok": 0, "consecutive_failures": 0, "slow_streak": 0, "last_check": None,
                        "last_latency_ms": None, "down_since": None, "incidents": []}

    # -- helpers --------------------------------------------------------
    def _instance_name(self) -> str:
        self._instances += 1
        return f"{_slug(self.key)[:30]}-i{self._instances}"

    def _incident(self, text: str) -> None:
        self.monitor["incidents"] = ([{"at": time.time(), "text": text}] + self.monitor["incidents"])[:20]

    def _start_healthy(self, release: Release) -> RunningApp | None:
        try:
            app = release.launch(self._instance_name())
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            log.warning("Could not start release %s: %s", release.sha[:8], exc)
            self.last_boot_log = str(exc)
            return None
        if app.wait_healthy(settings.prod_boot_timeout_seconds) is None:
            state = "exited" if not app.alive() else f"gave no healthy answer within {settings.prod_boot_timeout_seconds} s"
            self.last_boot_log = f"The app {state}. Last log lines:\n" + "\n".join(app.logs(20))
            app.remove()
            return None
        return app

    # -- release (blue-green) ------------------------------------------
    def release(self, clone_url: str, branch: str, git_env: dict | None, use_docker: bool) -> None:
        with self.lock:
            release = self._prepare(clone_url, branch, git_env, use_docker)
            self.releases.append(release)
            candidate = self._start_healthy(release)
            if candidate is None:
                self._block(release, "It did not start and answer its health check.", [], self.last_boot_log)
                return
            from app.services.validation import production

            results = production.verify_release(candidate)
            release.checks = [{"stage": s, "status": r.status, "report": r.stdout} for s, r in results]
            failed = [s for s, r in results if r.status in ("failed", "error")]
            if failed:
                candidate.remove()
                self._block(release, f"Failed live checks: {', '.join(production.STAGE_TITLES.get(s, s) for s in failed)}.",
                            [r for s, r in results if s in failed])
                return

            standby = self._start_healthy(release) if settings.standby_replica else None
            old_live, old_standby = self.router.live, self.router.standby
            self.router.switch(candidate, standby, release.sha)  # the switch: atomic, no request is dropped
            if old_standby is not None:
                old_standby.remove()
            if self.previous_app is not None:
                self.previous_app.remove()
            if self.previous is not None:
                self.previous.status = "retired"
            self.previous, self.previous_app = self.live, old_live
            self.previous_until = time.time() + settings.rollback_window_seconds
            if self.previous is not None:
                self.previous.status = "previous"
            release.status, self.live = "live", release
            self.open_path = _landing_path(self.url)
            self._prune()
            if self.previous is not None:
                _alert("INFO", f"Released {release.sha[:8]} with zero downtime",
                       f"{branch} #{release.number} passed its live checks and now serves {self.url}. "
                       f"The previous release {self.previous.sha[:8]} stays ready for rollback.", self.key)
            if standby is None and settings.standby_replica:
                _alert("WARNING", "Standby copy could not be started",
                       "The release is live but has no standby; a crash would cause a short outage.", self.key)

    def _prepare(self, clone_url: str, branch: str, git_env: dict | None, use_docker: bool) -> Release:
        from app.services import containerize
        from app.services.validation.sandbox import _force_rmtree, docker_available

        number = len(self.releases) + 1
        folder = _previews_root() / _slug(self.key) / f"r{number}"
        if folder.exists():
            _force_rmtree(folder)
        folder.parent.mkdir(parents=True, exist_ok=True)
        try:
            repo = Repo.clone_from(clone_url, folder, branch=branch, depth=1, env=git_env or {})
            sha = repo.head.commit.hexsha
            repo.close()
        except GitCommandError as exc:
            raise PreviewError(f"Could not download '{branch}': {(exc.stderr or str(exc)).strip()[-300:]}") from exc
        spec = containerize.detect(containerize.read_project_files(folder))
        image = ""
        if (folder / "Dockerfile").is_file() and use_docker and docker_available()[0]:
            image = f"i2d-release-{re.sub(r'[^a-z0-9]+', '-', self.key.lower()).strip('-')[:40]}:{sha[:12]}"
            build = subprocess.run(  # noqa: S603 - fixed argv
                [shutil.which("docker") or "docker", "build", "-t", image, "."], cwd=folder,
                capture_output=True, text=True, timeout=settings.docker_build_timeout_seconds,
            )
            if build.returncode != 0:
                raise PreviewError("Docker image build failed:\n" + "\n".join((build.stdout + build.stderr).splitlines()[-20:]))
        elif spec is None or spec.kind != "python-asgi":
            raise PreviewError(
                "This project can't be started automatically without Docker (no FastAPI app found). "
                f"Start Docker Desktop so staging runs from its Dockerfile, or run it by hand from a checkout of '{branch}'."
            )
        return Release(number, branch, sha, folder, spec.entry if spec else "", spec.port if spec else 8000,
                       spec.health_path if spec else "/", image)

    def _block(self, release: Release, reason: str, failures: list, extra: str = "") -> None:
        release.status, release.reason = "blocked", reason
        report = ("\n\n".join(r.stdout for r in failures) + ("\n" + extra if extra else "")).strip()[:3000]
        if self.live is not None:
            _alert("WARNING", f"Release {release.sha[:8]} blocked — live site unaffected",
                   f"{reason} {self.url} keeps serving {self.live.sha[:8]}.\n\n{report}", self.key)
            return
        _alert("CRITICAL", f"Release {release.sha[:8]} blocked — nothing is serving",
               f"{reason} This is the first release, so {self.url} has no working version.\n\n{report}", self.key)
        raise PreviewError(f"Release {release.sha[:8]} was not put live. {reason}\n{report}")

    def _prune(self) -> None:
        """Keep the folders of the live and previous releases (and the latest few)."""
        from app.services.validation.sandbox import _force_rmtree

        keep = {r.number for r in self.releases[-3:]} | {r.number for r in (self.live, self.previous) if r}
        for r in self.releases:
            if r.number not in keep and r.folder.exists():
                _force_rmtree(r.folder)

    # -- rollback ----------------------------------------------------------
    def rollback(self, reason: str = "Rolled back by a person.") -> None:
        with self.lock:
            if self.previous is None:
                raise PreviewError("There is no previous release to roll back to.")
            target, app = self.previous, self.previous_app
            if app is None or not app.healthy():
                if app is not None:
                    app.remove()
                if not target.folder.exists():
                    raise PreviewError(f"Release {target.sha[:8]} is no longer available to roll back to.")
                app = self._start_healthy(target)
                if app is None:
                    raise PreviewError(f"Release {target.sha[:8]} did not start, so the current release stays live.")
            standby = self._start_healthy(target) if settings.standby_replica else None
            old_live, old_standby = self.router.live, self.router.standby
            self.router.switch(app, standby, target.sha)
            if old_standby is not None:
                old_standby.remove()
            failed = self.live
            if failed is not None:
                failed.status = "previous"
            self.previous, self.previous_app = failed, old_live
            self.previous_until = time.time() + settings.rollback_window_seconds
            target.status, self.live = "live", target
            self._incident(f"Rolled back to {target.sha[:8]}: {reason}")
            _alert("WARNING", f"Rolled back to {target.sha[:8]}", reason, self.key)

    # -- self-healing -------------------------------------------------------
    def _upstream_failed(self, instance: RunningApp, promoted: bool) -> None:
        if promoted:
            self._incident("Live copy stopped responding; the standby took over instantly.")
            _alert("CRITICAL", "Live copy failed — standby took over (no downtime)",
                   "Requests are now served by the standby copy. A replacement standby is being started.\n\nLast log lines:\n"
                   + "\n".join(instance.logs(15)), self.key)
            with self.lock:
                instance.remove()
                self._replace_standby()

    def _replace_standby(self) -> None:
        if not settings.standby_replica or self.live is None or self.router.standby is not None:
            return
        standby = self._start_healthy(self.live)
        if standby is None:
            _alert("WARNING", "Standby copy could not be restarted",
                   "The site is up, but a further crash would cause a short outage until it is restarted.", self.key)
            return
        self.router.switch(self.router.live, standby)

    def check(self) -> None:
        """One watchdog tick: measure what users see, heal what is broken."""
        if not self.lock.acquire(blocking=False):
            return  # a release or heal is in progress
        try:
            if not self.router.alive:
                self._restart_router()
            m = self.monitor
            started = time.monotonic()
            try:
                ok = httpx.get(self.url + (self.live.health_path if self.live else "/"), timeout=5).status_code < 400
            except httpx.HTTPError:
                ok = False
            latency = (time.monotonic() - started) * 1000
            m.update(checks=m["checks"] + 1, last_check=time.time(), last_latency_ms=round(latency))
            live = self.router.live
            if ok and live is not None and live.healthy():
                m["ok"] += 1
                if m["down_since"] is not None:
                    down_for = time.time() - m["down_since"]
                    self._incident(f"Recovered after {down_for:.0f} s.")
                    _alert("INFO", "Site recovered", f"{self.url} is answering again after {down_for:.0f} s.", self.key)
                m.update(consecutive_failures=0, down_since=None)
                m["slow_streak"] = m["slow_streak"] + 1 if latency > settings.prod_p95_budget_ms else 0
                if m["slow_streak"] == 3:
                    _alert("WARNING", "Site is responding slowly",
                           f"Health checks took {latency:.0f} ms (budget {settings.prod_p95_budget_ms} ms) three times in a row.", self.key)
            elif live is not None:
                if ok:
                    m["ok"] += 1  # users were served (by the standby) even though the live copy is unwell
                m["consecutive_failures"] += 1
                if m["consecutive_failures"] >= settings.monitor_failure_threshold:
                    self._heal(user_impact=not ok)
            standby = self.router.standby
            if standby is not None and not standby.healthy():
                self.router.switch(self.router.live, None)
                standby.remove()
                self._incident("Standby copy failed its health check and was replaced.")
                self._replace_standby()
            if self.previous_app is not None and time.time() > self.previous_until:
                self.previous_app.remove()
                self.previous_app = None
        finally:
            self.lock.release()

    def _heal(self, user_impact: bool) -> None:
        m = self.monitor
        if user_impact and m["down_since"] is None:
            m["down_since"] = time.time()
        broken = self.router.live
        standby = self.router.standby
        if standby is not None and standby.healthy():
            self.router.switch(standby, None)
            self.router.stats["failovers"] += 1
            if broken is not None:
                broken.remove()
            self._incident("Live copy failed health checks; the standby took over.")
            _alert("CRITICAL", "Live copy failed — standby took over (no downtime)",
                   "The watchdog moved traffic to the standby copy. A replacement standby is being started.", self.key)
            self._replace_standby()
        elif self.previous_app is not None and self.previous_app.healthy():
            self.rollback(f"Release {self.live.sha[:8] if self.live else '?'} failed health checks repeatedly; "
                          "the watchdog rolled back automatically.")
            if broken is not None:
                broken.remove()
                self.previous_app = None  # the failed release is not kept warm
        elif self.live is not None:
            self._incident("Live copy failed and there was no healthy standby; restarting it.")
            replacement = self._start_healthy(self.live)
            if replacement is None:
                _alert("CRITICAL", "Site is DOWN and could not be restarted",
                       f"{self.url} shows a maintenance page. Last log lines:\n" + "\n".join(broken.logs(20) if broken else []),
                       self.key)
                return
            self.router.switch(replacement, None)
            if broken is not None:
                broken.remove()
            _alert("CRITICAL", "Site was restarted after failing",
                   "There was no healthy standby, so the release was restarted.", self.key)
            self._replace_standby()
        m["consecutive_failures"] = 0

    def _restart_router(self) -> None:
        live, standby, sha = self.router.live, self.router.standby, self.router.release_sha
        self.router = Router(self.key, self.port, self._upstream_failed)
        self.router.switch(live, standby, sha)
        self.router.start()
        self._incident("Traffic router stopped and was restarted.")
        _alert("CRITICAL", "Traffic router restarted", f"The router on port {self.port} had stopped; it was restarted.", self.key)

    # -- lifecycle / status ---------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        with self.lock:
            for app in {id(a): a for a in (self.router.live, self.router.standby, self.previous_app) if a}.values():
                app.remove()
            self.router.switch(None, None)
            self.router.stop()

    def info(self) -> dict:
        live, standby = self.router.live, self.router.standby
        m = self.monitor
        availability = round(100 * m["ok"] / m["checks"], 2) if m["checks"] else None
        return {
            "running": live is not None,
            "strategy": "blue-green + hot standby",
            "mode": "docker" if self.live and self.live.image else "python",
            "url": self.url,
            "open_url": self.url + self.open_path,
            "port": self.port,
            "branch": self.live.branch if self.live else "",
            "sha": self.live.sha[:8] if self.live else "",
            "release": self.live.number if self.live else None,
            "started_at": self.live.created_at if self.live else self.started_at,
            "exit_code": None,
            "log": live.logs(30) if live else [],
            "standby": standby is not None,
            "previous": ({"sha": self.previous.sha[:8], "number": self.previous.number, "warm": self.previous_app is not None,
                          "warm_until": self.previous_until if self.previous_app else None} if self.previous else None),
            "monitor": {**{k: v for k, v in m.items() if k != "incidents"}, "availability": availability,
                        "enabled": settings.monitor_enabled, "interval_seconds": settings.monitor_interval_seconds,
                        "incidents": m["incidents"]},
            "traffic": dict(self.router.stats),
            "releases": [r.summary() for r in reversed(self.releases[-10:])],
            "last_release": self.releases[-1].summary() if self.releases else None,
        }


# ---------------------------------------------------------------------------
# Public API (used by app/services/github/delivery.py)
# ---------------------------------------------------------------------------
_DEPLOYMENTS: dict[str, Deployment] = {}
_registry_lock = threading.Lock()
_watchdog: threading.Thread | None = None


def start(
    key: str, clone_url: str, branch: str, git_env: dict | None = None, wait_seconds: float = 8.0, use_docker: bool = True
) -> dict:
    """Release `branch` from `clone_url` to `key`'s stable address with zero
    downtime. A release that fails its live checks is not switched to."""
    with _registry_lock:
        deployment = _DEPLOYMENTS.get(key)
        if deployment is None:
            deployment = Deployment(key, _free_port(key))
            deployment.router.start()
            _DEPLOYMENTS[key] = deployment
    try:
        deployment.release(clone_url, branch, git_env, use_docker)
    except PreviewError:
        if deployment.live is None:  # nothing ever went live: don't keep an empty address around
            stop(key)
        raise
    _ensure_watchdog()
    return info(key)


def info(key: str) -> dict:
    deployment = _DEPLOYMENTS.get(key)
    return deployment.info() if deployment else {"running": False}


def stop(key: str) -> dict:
    with _registry_lock:
        deployment = _DEPLOYMENTS.pop(key, None)
    if deployment is not None:
        deployment.stop()
    return {"running": False}


def rollback(key: str) -> dict:
    deployment = _DEPLOYMENTS.get(key)
    if deployment is None:
        raise PreviewError("Nothing is deployed for this project.")
    deployment.rollback()
    return info(key)


def all_deployments() -> list[dict]:
    return [{"key": k, **d.info()} for k, d in list(_DEPLOYMENTS.items())]


def check_now(key: str) -> None:
    """Run one watchdog tick immediately (used by tests and the UI)."""
    deployment = _DEPLOYMENTS.get(key)
    if deployment is not None:
        deployment.check()


def _ensure_watchdog() -> None:
    global _watchdog
    if not settings.monitor_enabled or (_watchdog is not None and _watchdog.is_alive()):
        return
    _watchdog = threading.Thread(target=_watch, daemon=True, name="deployment-watchdog")
    _watchdog.start()


def _watch() -> None:
    while _DEPLOYMENTS:
        time.sleep(settings.monitor_interval_seconds)
        for deployment in list(_DEPLOYMENTS.values()):
            try:
                deployment.check()
            except Exception:  # noqa: BLE001 - the watchdog must keep running
                log.exception("Watchdog check failed for %s", deployment.key)


def _landing_path(base_url: str) -> str:
    """API-only apps have no page at "/"; send people to their docs instead."""

    def _ok(path: str) -> bool:
        try:
            return httpx.get(base_url + path, timeout=3).status_code < 400
        except httpx.HTTPError:
            return False

    return "/" if _ok("/") else ("/docs" if _ok("/docs") else "/")
