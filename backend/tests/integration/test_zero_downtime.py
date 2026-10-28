"""Zero-downtime deployments: failures raise alerts, they never take the site
down. A broken release is never switched to, a crashed copy is replaced by
the hot standby on the next request, traffic keeps flowing during a release,
and the watchdog heals (failover, rollback, restart)."""
from __future__ import annotations

import threading
import time

import httpx
import pytest
from git import Actor, Repo
from sqlmodel import Session, select

from app.core import config
from app.models.models import Alert
from app.services import alerts, preview
from app.services.greenfield import templates

AUTHOR = Actor("Test", "test@example.com")
KEY = "acme/shop@staging"
INTENT = "Build a REST API for managing books"


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(config.settings, "prod_load_requests", 40)
    monkeypatch.setattr(config.settings, "prod_load_concurrency", 4)
    monkeypatch.setattr(config.settings, "prod_boot_timeout_seconds", 60)
    monkeypatch.setattr(config.settings, "monitor_enabled", False)  # ticks are driven by the tests
    monkeypatch.setattr(config.settings, "monitor_failure_threshold", 1)
    yield
    preview.stop(KEY)


@pytest.fixture
def repo(tmp_path):
    src = tmp_path / "proj"
    src.mkdir()
    for f in templates.files(INTENT, templates.design(INTENT)):
        (src / f["path"]).parent.mkdir(parents=True, exist_ok=True)
        (src / f["path"]).write_text(f["content"], encoding="utf-8")
    r = Repo.init(src, initial_branch="staging")
    r.git.add(A=True)
    r.index.commit("v1", author=AUTHOR, committer=AUTHOR)
    yield src, r
    r.close()


def _commit(src, r, message: str, edit=None) -> str:
    main = src / "app" / "main.py"
    text = main.read_text(encoding="utf-8")
    main.write_text(edit(text) if edit else text + f"\n# {message}\n", encoding="utf-8")
    r.git.add(A=True)
    return r.index.commit(message, author=AUTHOR, committer=AUTHOR).hexsha


def _break_list_endpoint(text: str) -> str:
    return text.replace("    return store.list(q, status, sort)", "    raise RuntimeError('bug in v2')")


def _alerts(title_part: str) -> list[Alert]:
    with Session(alerts._engine()) as s:
        return [a for a in s.exec(select(Alert)).all() if title_part in a.title]


def _served_release(url: str) -> str:
    return httpx.get(url + "/health", timeout=5).headers.get("x-release", "")


def test_broken_release_is_blocked_and_the_live_site_keeps_serving(repo, fast):
    src, r = repo
    info = preview.start(KEY, str(src), "staging")
    v1 = info["sha"]
    assert info["running"] and info["standby"] and info["strategy"].startswith("blue-green")

    v2 = _commit(src, r, "v2", _break_list_endpoint)
    info = preview.start(KEY, str(src), "staging")  # does not raise: the old version is still live
    assert info["sha"] == v1 and info["last_release"]["status"] == "blocked"
    assert "Smoke test" in info["last_release"]["reason"]
    assert _served_release(info["url"]) == v1[:8]
    assert httpx.get(info["url"] + "/api/books", timeout=5).status_code == 200  # users never saw v2's bug
    blocked = _alerts(f"Release {v2[:8]} blocked")
    assert blocked and blocked[0].severity == "WARNING" and "live site unaffected" in blocked[0].title


def test_first_release_that_fails_raises_and_alerts(repo, fast):
    src, r = repo
    _commit(src, r, "broken", _break_list_endpoint)
    with pytest.raises(preview.PreviewError, match="was not put live"):
        preview.start(KEY, str(src), "staging")
    assert preview.info(KEY) == {"running": False}
    assert _alerts("nothing is serving")[0].severity == "CRITICAL"


def test_no_request_fails_while_a_new_release_goes_live(repo, fast):
    src, r = repo
    info = preview.start(KEY, str(src), "staging")
    url, failures, served = info["url"], [], []
    stop = threading.Event()

    def traffic():
        with httpx.Client(timeout=5) as client:
            while not stop.is_set():
                try:
                    resp = client.get(url + "/api/books")
                    served.append(resp.headers.get("x-release"))
                    if resp.status_code != 200:
                        failures.append(resp.status_code)
                except httpx.HTTPError as exc:
                    failures.append(repr(exc))

    worker = threading.Thread(target=traffic)
    worker.start()
    try:
        v2 = _commit(src, r, "v2")
        info = preview.start(KEY, str(src), "staging")
        time.sleep(0.5)
    finally:
        stop.set()
        worker.join()
    assert info["sha"] == v2[:8] and info["previous"]["sha"] == info["releases"][1]["sha"]
    assert failures == [] and len(served) > 20
    assert served[0] != v2[:8] and served[-1] == v2[:8]  # traffic moved from v1 to v2 without a single error


def test_crashed_live_copy_fails_over_to_standby_without_downtime(repo, fast):
    src, _ = repo
    info = preview.start(KEY, str(src), "staging")
    deployment = preview._DEPLOYMENTS[KEY]
    deployment.router.live.process.kill()  # simulate a crash
    resp = httpx.get(info["url"] + "/api/books", timeout=10)
    assert resp.status_code == 200  # the very next request is served by the standby
    deadline = time.time() + 30
    while time.time() < deadline and preview.info(KEY)["standby"] is False:
        time.sleep(0.5)
    info = preview.info(KEY)
    assert info["standby"] and info["traffic"]["failovers"] == 1  # a new standby replaced the crashed copy
    assert _alerts("standby took over")[0].severity == "CRITICAL"


def test_rollback_restores_the_previous_release(repo, fast):
    src, r = repo
    v1 = preview.start(KEY, str(src), "staging")["sha"]
    _commit(src, r, "v2")
    assert preview.start(KEY, str(src), "staging")["sha"] != v1
    info = preview.rollback(KEY)
    assert info["sha"] == v1 and _served_release(info["url"]) == v1
    assert _alerts(f"Rolled back to {v1}")


def test_watchdog_restarts_a_failed_site_when_there_is_no_standby(repo, fast, monkeypatch):
    monkeypatch.setattr(config.settings, "standby_replica", False)
    src, _ = repo
    info = preview.start(KEY, str(src), "staging")
    preview._DEPLOYMENTS[KEY].router.live.process.kill()
    assert httpx.get(info["url"] + "/health", timeout=5).status_code == 503  # maintenance page, not a hang
    preview.check_now(KEY)  # watchdog tick: detects it and restarts the release
    assert httpx.get(info["url"] + "/health", timeout=5).status_code == 200
    preview.check_now(KEY)
    info = preview.info(KEY)
    assert info["monitor"]["incidents"][0]["text"].startswith("Recovered")
    assert _alerts("Site was restarted") and _alerts("Site recovered")


def test_alerts_are_sent_to_the_webhook(monkeypatch):
    sent = []

    class _Resp:
        status_code = 200

    monkeypatch.setattr(config.settings, "alert_webhook_url", "https://hooks.example.test/x")
    monkeypatch.setattr(alerts.httpx, "post", lambda url, json, timeout: sent.append((url, json)) or _Resp())
    alert = alerts.raise_alert("CRITICAL", "monitor", "Site is DOWN", "details", deployment=KEY)
    assert alert.delivered_to == "webhook" and "Site is DOWN" in sent[0][1]["text"]
    assert alerts.raise_alert("CRITICAL", "monitor", "Site is DOWN", "again", deployment=KEY) is None  # no flood


def test_alert_and_deployment_endpoints():
    from fastapi.testclient import TestClient

    from app.main import app

    alerts.raise_alert("WARNING", "monitor", "Site is responding slowly", "p95 2400 ms", deployment=KEY)
    client = TestClient(app)
    body = client.get("/api/alerts", params={"open_only": True}).json()
    assert body["open"]["WARNING"] == 1 and body["alerts"][0]["title"] == "Site is responding slowly"
    assert client.post(f"/api/alerts/{body['alerts'][0]['id']}/ack").json()["open"]["WARNING"] == 0
    assert client.post("/api/alerts/missing/ack").status_code == 404
    assert client.get("/api/deployments").json() == {"deployments": []}
