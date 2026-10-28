"""Built-in general-purpose full-stack web app template (mock mode).

Used for any request that no specialised template covers: a branded,
interactive single-page app (dashboard stats, search, status filters,
sorting, create/edit/delete in a validated dialog, toasts, empty states,
responsive, dark mode) on a FastAPI backend with a REST API, tests, CI and
Docker. Labels come from the request ("flight booking" -> "Bookings").
Placeholders: __TITLE__, __RESOURCE__/__RESOURCES__ (route/data names),
__RESOURCE_LABEL__/__RESOURCES_LABEL__ (UI labels), __INTENT__, __PORT__,
__WHERE_IT_RUNS__ — filled by templates.files().
"""
from __future__ import annotations


def design(title: str, resource: str, resources: str) -> dict:
    label, labels = resource.replace("-", " ").title(), resources.replace("-", " ").title()
    return {
        "project_name": title.lower().replace(" ", "-") + "-app",
        "summary": f"{title}: a full-stack web app to manage {labels.lower()} — an interactive dashboard with search, "
        f"filters and create/edit/delete, backed by a FastAPI REST API with validation, tests, CI and Docker.",
        "requirements": [
            f"The home page shows {labels.lower()} with live counts by status.",
            f"Users can create, edit and delete {labels.lower()} in a form with clear validation messages.",
            f"Users can search {labels.lower()} by name or description, filter by status and sort the list.",
            f"Every action is also available through a REST API at /api/{resources}.",
            "The interface gives instant feedback (toasts, loading and empty states) and works on mobile.",
        ],
        "non_functional": [
            "Input is validated on the server; the browser checks are only for convenience.",
            "Responsive layout with automatic dark mode.",
            "No external services are needed to run or test the app.",
        ],
        "acceptance_criteria": [
            "GET / serves the interactive app.",
            f"POST /api/{resources} creates a {label.lower()}; invalid input returns 422.",
            f"GET /api/{resources} supports q, status and sort; GET /api/{resources}/stats returns counts by status.",
            f"PUT and DELETE /api/{resources}/{{id}} update and remove; unknown ids return 404.",
            "The automated test suite passes.",
        ],
        "stack": "Python 3 · FastAPI · vanilla HTML/CSS/JavaScript (single page) · pytest",
        "components": [
            {"name": "Web UI", "responsibility": f"Dashboard, {labels.lower()} list, search/filters and the edit dialog.",
             "files": ["static/index.html", "static/styles.css", "static/app.js"]},
            {"name": "API", "responsibility": "Page, REST endpoints and validation.",
             "files": ["app/__init__.py", "app/main.py", "app/models.py"]},
            {"name": "Store", "responsibility": "Storage, search, filtering, sorting and stats.", "files": ["app/store.py"]},
            {"name": "Tests", "responsibility": "Store and API tests.", "files": ["tests/test_store.py", "tests/test_api.py"]},
            {"name": "Project config", "responsibility": "Dependencies, test and lint configuration, docs.",
             "files": ["requirements.txt", "pytest.ini", "pyproject.toml", "README.md"]},
            {"name": "CI pipeline", "responsibility": "GitHub Actions: lint, security scan and tests.",
             "files": [".github/workflows/ci.yml"]},
        ],
        "files": [
            {"path": "app/__init__.py", "purpose": "Package marker."},
            {"path": "app/models.py", "purpose": "Request/response models with validation."},
            {"path": "app/store.py", "purpose": "Storage, search, filters, sorting, stats."},
            {"path": "app/main.py", "purpose": "FastAPI app: page, REST API, health."},
            {"path": "static/index.html", "purpose": "App shell."},
            {"path": "static/styles.css", "purpose": "Responsive styling with dark mode."},
            {"path": "static/app.js", "purpose": "Interactive dashboard, list and edit dialog."},
            {"path": "tests/test_store.py", "purpose": "Store tests."},
            {"path": "tests/test_api.py", "purpose": "API and page tests."},
            {"path": "requirements.txt", "purpose": "Runtime and test dependencies."},
            {"path": "pytest.ini", "purpose": "Test discovery configuration."},
            {"path": "pyproject.toml", "purpose": "Ruff lint configuration."},
            {"path": "README.md", "purpose": "How to run, use and test the app."},
            {"path": ".github/workflows/ci.yml", "purpose": "GitHub Actions CI."},
        ],
        "dependencies": ["fastapi", "uvicorn", "httpx (tests)", "pytest (tests)"],
        "test_command": "python3 -m pytest -q",
        "run_command": "uvicorn app.main:app --reload --port __PORT__",
        "risks": [f"{labels} are kept in memory and are lost on restart; a database is needed before production use."],
        "template": "web_app",
    }


MODELS_PY = r'''"""Request/response models. Validation happens here, on the server."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["pending", "confirmed", "completed", "cancelled"]
STATUSES: tuple[str, ...] = ("pending", "confirmed", "completed", "cancelled")


class RecordIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=2000)
    status: Status = "pending"
    date: dt.date | None = None


class Record(RecordIn):
    id: int
    created_at: str
    updated_at: str
'''

STORE_PY = r'''"""In-memory storage with search, filtering, sorting and stats."""
from __future__ import annotations

import datetime as dt

from app.models import STATUSES, Record, RecordIn

SORTS = ("newest", "oldest", "name", "date")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class RecordStore:
    def __init__(self) -> None:
        self._records: dict[int, Record] = {}
        self._next_id = 1

    def create(self, data: RecordIn) -> Record:
        now = _now()
        record = Record(id=self._next_id, created_at=now, updated_at=now, **data.model_dump())
        self._records[record.id] = record
        self._next_id += 1
        return record

    def get(self, record_id: int) -> Record | None:
        return self._records.get(record_id)

    def update(self, record_id: int, data: RecordIn) -> Record | None:
        current = self._records.get(record_id)
        if current is None:
            return None
        record = Record(id=record_id, created_at=current.created_at, updated_at=_now(), **data.model_dump())
        self._records[record_id] = record
        return record

    def delete(self, record_id: int) -> bool:
        return self._records.pop(record_id, None) is not None

    def list(self, q: str = "", status: str = "", sort: str = "newest") -> list[Record]:
        term = q.strip().lower()
        items = [
            r for r in self._records.values()
            if (not status or r.status == status)
            and (not term or term in r.name.lower() or term in r.description.lower())
        ]
        if sort == "oldest":
            items.sort(key=lambda r: r.id)
        elif sort == "name":
            items.sort(key=lambda r: r.name.lower())
        elif sort == "date":
            items.sort(key=lambda r: (r.date is None, r.date or dt.date.max))
        else:
            items.sort(key=lambda r: -r.id)
        return items

    def stats(self) -> dict:
        counts = {s: 0 for s in STATUSES}
        for r in self._records.values():
            counts[r.status] += 1
        return {"total": len(self._records), **counts}
'''

MAIN_PY = r'''"""__TITLE__: web app + REST API."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.models import Record, RecordIn
from app.store import RecordStore

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="__TITLE__")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
store = RecordStore()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/__RESOURCES__", response_model=list[Record])
def list_records(
    q: str = Query(default="", max_length=100),
    status: Literal["", "pending", "confirmed", "completed", "cancelled"] = "",
    sort: Literal["newest", "oldest", "name", "date"] = "newest",
) -> list[Record]:
    return store.list(q, status, sort)


@app.get("/api/__RESOURCES__/stats")
def stats() -> dict:
    return store.stats()


@app.post("/api/__RESOURCES__", response_model=Record, status_code=201)
def create(body: RecordIn) -> Record:
    return store.create(body)


@app.get("/api/__RESOURCES__/{record_id}", response_model=Record)
def get_one(record_id: int) -> Record:
    record = store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="__RESOURCE_LABEL__ not found")
    return record


@app.put("/api/__RESOURCES__/{record_id}", response_model=Record)
def update(record_id: int, body: RecordIn) -> Record:
    record = store.update(record_id, body)
    if record is None:
        raise HTTPException(status_code=404, detail="__RESOURCE_LABEL__ not found")
    return record


@app.delete("/api/__RESOURCES__/{record_id}", status_code=204)
def delete(record_id: int) -> Response:
    if not store.delete(record_id):
        raise HTTPException(status_code=404, detail="__RESOURCE_LABEL__ not found")
    return Response(status_code=204)
'''

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="logo" aria-hidden="true">__INITIAL__</span>__TITLE__</div>
    <button class="btn primary" id="new-btn">+ New __RESOURCE_LABEL__</button>
  </header>

  <main class="container">
    <section class="hero">
      <h1>__RESOURCES_LABEL__</h1>
      <p>Create, track and manage your __RESOURCES_LOWER__ in one place.</p>
    </section>

    <section class="stats" id="stats" aria-label="Summary"></section>

    <section class="toolbar">
      <input id="search" type="search" placeholder="Search __RESOURCES_LOWER__…" aria-label="Search" />
      <div class="chips" id="status-chips" role="group" aria-label="Filter by status"></div>
      <select id="sort" aria-label="Sort">
        <option value="newest">Newest first</option>
        <option value="oldest">Oldest first</option>
        <option value="name">Name A–Z</option>
        <option value="date">Date</option>
      </select>
    </section>

    <section id="list" class="list" aria-live="polite"></section>
  </main>

  <div class="overlay" id="overlay" hidden>
    <form class="dialog" id="form" novalidate aria-labelledby="form-title">
      <h2 id="form-title">New __RESOURCE_LABEL__</h2>
      <label for="f-name">Name</label>
      <input id="f-name" maxlength="120" required />
      <p class="error" data-for="f-name"></p>
      <label for="f-description">Description</label>
      <textarea id="f-description" rows="3" maxlength="2000"></textarea>
      <div class="row">
        <div>
          <label for="f-status">Status</label>
          <select id="f-status">
            <option value="pending">Pending</option>
            <option value="confirmed">Confirmed</option>
            <option value="completed">Completed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
        <div>
          <label for="f-date">Date</label>
          <input id="f-date" type="date" />
        </div>
      </div>
      <div class="actions">
        <button type="button" class="btn" id="cancel-btn">Cancel</button>
        <button type="submit" class="btn primary" id="save-btn">Save</button>
      </div>
    </form>
  </div>

  <div class="toast" id="toast" role="status" hidden></div>
  <script src="/static/app.js"></script>
</body>
</html>
'''

STYLES_CSS = r''':root {
  --accent: #4f46e5;
  --accent-dark: #4338ca;
  --bg: #f5f6fa;
  --card: #ffffff;
  --text: #111827;
  --muted: #6b7280;
  --line: #e5e7eb;
  --danger: #dc2626;
  --pending: #d97706;
  --confirmed: #2563eb;
  --completed: #16a34a;
  --cancelled: #6b7280;
  --radius: 14px;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1117; --card: #181b24; --text: #e5e7eb; --muted: #9ca3af; --line: #2a2f3a; }
}
* { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
button, input, select, textarea { font: inherit; color: inherit; }
.container { max-width: 1040px; margin: 0 auto; padding: 20px 16px 60px; }

.topbar { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 20px; background: var(--card); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 18px; }
.logo { width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; color: #fff; background: linear-gradient(135deg, var(--accent), #7c3aed); }

.hero { padding: 26px 24px; border-radius: var(--radius); color: #fff; background: linear-gradient(120deg, var(--accent), #7c3aed); margin-bottom: 18px; }
.hero h1 { margin: 0 0 4px; font-size: 28px; }
.hero p { margin: 0; opacity: .9; }

.stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 18px; }
.stat { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px; cursor: pointer; transition: transform .12s, border-color .12s; text-align: left; }
.stat:hover { transform: translateY(-2px); border-color: var(--accent); }
.stat.active { border-color: var(--accent); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 25%, transparent); }
.stat .value { font-size: 26px; font-weight: 800; }
.stat .label { color: var(--muted); font-size: 13px; }

.toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
.toolbar input[type=search] { flex: 1; min-width: 200px; }
input, select, textarea { padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); }
input:focus, select:focus, textarea:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
input[aria-invalid="true"] { border-color: var(--danger); }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { border: 1px solid var(--line); background: var(--card); border-radius: 20px; padding: 6px 12px; cursor: pointer; font-size: 13px; }
.chip.active { background: var(--accent); border-color: var(--accent); color: #fff; }

.list { display: grid; gap: 10px; }
.item { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; display: flex; gap: 14px; align-items: flex-start; animation: rise .18s ease-out; }
@keyframes rise { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
.item .main { flex: 1; min-width: 0; }
.item h3 { margin: 0 0 4px; font-size: 16px; overflow-wrap: anywhere; }
.item p { margin: 4px 0 0; color: var(--muted); font-size: 14px; overflow-wrap: anywhere; }
.meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12.5px; color: var(--muted); }
.badge { font-size: 12px; font-weight: 700; padding: 2px 9px; border-radius: 20px; color: #fff; text-transform: capitalize; }
.badge.pending { background: var(--pending); }
.badge.confirmed { background: var(--confirmed); }
.badge.completed { background: var(--completed); }
.badge.cancelled { background: var(--cancelled); }
.item .buttons { display: flex; gap: 6px; }

.btn { border: 1px solid var(--line); background: var(--card); border-radius: 10px; padding: 9px 14px; cursor: pointer; font-weight: 600; }
.btn:hover { border-color: var(--accent); }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn.primary:hover { background: var(--accent-dark); }
.btn.danger { color: var(--danger); }
.btn:disabled { opacity: .6; cursor: wait; }

.empty { text-align: center; padding: 50px 20px; color: var(--muted); background: var(--card); border: 1px dashed var(--line); border-radius: var(--radius); }
.empty .big { font-size: 44px; }
.skeleton { height: 70px; border-radius: 12px; background: linear-gradient(90deg, var(--card), var(--line), var(--card)); background-size: 200% 100%; animation: shimmer 1.2s infinite; }
@keyframes shimmer { to { background-position: -200% 0; } }

.overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: grid; place-items: center; z-index: 20; padding: 16px; }
.dialog { width: min(520px, 100%); background: var(--card); border-radius: var(--radius); padding: 22px; box-shadow: 0 20px 50px rgba(0,0,0,.3); animation: rise .15s ease-out; }
.dialog h2 { margin: 0 0 12px; }
.dialog label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 4px; }
.dialog input, .dialog textarea, .dialog select { width: 100%; }
.dialog .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.dialog .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.error { color: var(--danger); font-size: 12.5px; min-height: 16px; margin: 3px 0 0; }

.toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); background: var(--text); color: var(--bg); padding: 11px 18px; border-radius: 10px; z-index: 30; font-size: 14px; }
.toast.error { background: var(--danger); color: #fff; }

@media (max-width: 760px) {
  .stats { grid-template-columns: repeat(3, 1fr); }
  .hero h1 { font-size: 22px; }
  .item { flex-direction: column; }
  .dialog .row { grid-template-columns: 1fr; }
}
'''

APP_JS = r'''(() => {
  "use strict";
  const API = "/api/__RESOURCES__";
  const LABEL = "__RESOURCE_LABEL__";
  const STATUSES = ["pending", "confirmed", "completed", "cancelled"];
  const state = { q: "", status: "", sort: "newest", editing: null, items: [] };
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  async function api(path, options = {}) {
    const resp = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    if (resp.status === 204) return null;
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = Array.isArray(body.detail) ? body.detail.map((d) => `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg}`).join("; ") : body.detail;
      throw new Error(detail || `Request failed (${resp.status})`);
    }
    return body;
  }

  function toast(text, isError = false) {
    const el = $("toast");
    el.textContent = text;
    el.className = `toast${isError ? " error" : ""}`;
    el.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => (el.hidden = true), 2600);
  }

  // ---- Stats & filters -------------------------------------------------------
  async function loadStats() {
    const s = await api(`${API}/stats`);
    const cards = [["", "All", s.total], ...STATUSES.map((k) => [k, cap(k), s[k]])];
    $("stats").innerHTML = cards.map(([key, label, value]) =>
      `<button class="stat ${state.status === key ? "active" : ""}" data-status="${key}"><div class="value">${value}</div><div class="label">${label}</div></button>`
    ).join("");
    $("stats").querySelectorAll(".stat").forEach((b) => (b.onclick = () => setStatus(b.dataset.status)));
  }

  function renderChips() {
    $("status-chips").innerHTML = ["", ...STATUSES].map((k) =>
      `<button class="chip ${state.status === k ? "active" : ""}" data-status="${k}">${k ? cap(k) : "All"}</button>`
    ).join("");
    $("status-chips").querySelectorAll(".chip").forEach((b) => (b.onclick = () => setStatus(b.dataset.status)));
  }

  function setStatus(status) {
    state.status = status;
    renderChips();
    refresh();
  }

  // ---- List ---------------------------------------------------------------------
  async function loadList() {
    const params = new URLSearchParams({ q: state.q, status: state.status, sort: state.sort });
    state.items = await api(`${API}?${params}`);
    const list = $("list");
    if (!state.items.length) {
      const filtered = state.q || state.status;
      list.innerHTML = `<div class="empty"><div class="big">${filtered ? "🔍" : "✨"}</div>
        <h3>${filtered ? `No ${LABEL.toLowerCase()} matches your filters` : `No ${"__RESOURCES_LOWER__"} yet`}</h3>
        ${filtered ? `<button class="btn" id="clear">Clear filters</button>` : `<button class="btn primary" id="first">+ Create your first ${LABEL.toLowerCase()}</button>`}</div>`;
      if ($("clear")) $("clear").onclick = () => { state.q = ""; $("search").value = ""; setStatus(""); };
      if ($("first")) $("first").onclick = () => openForm();
      return;
    }
    list.innerHTML = state.items.map((r) => `
      <article class="item">
        <div class="main">
          <h3>${esc(r.name)}</h3>
          <div class="meta">
            <span class="badge ${r.status}">${r.status}</span>
            ${r.date ? `<span>📅 ${esc(new Date(r.date + "T00:00:00").toLocaleDateString())}</span>` : ""}
            <span>#${r.id}</span>
          </div>
          ${r.description ? `<p>${esc(r.description)}</p>` : ""}
        </div>
        <div class="buttons">
          <button class="btn" data-edit="${r.id}">Edit</button>
          <button class="btn danger" data-delete="${r.id}">Delete</button>
        </div>
      </article>`).join("");
    list.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => openForm(state.items.find((r) => r.id === Number(b.dataset.edit)))));
    list.querySelectorAll("[data-delete]").forEach((b) => (b.onclick = () => remove(Number(b.dataset.delete))));
  }

  async function refresh() {
    try {
      await Promise.all([loadStats(), loadList()]);
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function remove(id) {
    const item = state.items.find((r) => r.id === id);
    if (!confirm(`Delete “${item ? item.name : LABEL}”? This can't be undone.`)) return;
    try {
      await api(`${API}/${id}`, { method: "DELETE" });
      toast(`${LABEL} deleted`);
      refresh();
    } catch (e) {
      toast(e.message, true);
    }
  }

  // ---- Create / edit dialog -------------------------------------------------------
  function openForm(record = null) {
    state.editing = record;
    $("form-title").textContent = record ? `Edit ${LABEL}` : `New ${LABEL}`;
    $("f-name").value = record?.name ?? "";
    $("f-description").value = record?.description ?? "";
    $("f-status").value = record?.status ?? "pending";
    $("f-date").value = record?.date ?? "";
    setError("");
    $("overlay").hidden = false;
    $("f-name").focus();
  }

  function closeForm() {
    $("overlay").hidden = true;
    state.editing = null;
  }

  function setError(text) {
    document.querySelector('.error[data-for="f-name"]').textContent = text;
    $("f-name").setAttribute("aria-invalid", String(Boolean(text)));
  }

  async function save(event) {
    event.preventDefault();
    const name = $("f-name").value.trim();
    if (name.length < 2) { setError("Name must be at least 2 characters."); return; }
    setError("");
    const body = {
      name,
      description: $("f-description").value.trim(),
      status: $("f-status").value,
      date: $("f-date").value || null,
    };
    const btn = $("save-btn");
    btn.disabled = true;
    try {
      if (state.editing) {
        await api(`${API}/${state.editing.id}`, { method: "PUT", body: JSON.stringify(body) });
        toast(`${LABEL} updated`);
      } else {
        await api(API, { method: "POST", body: JSON.stringify(body) });
        toast(`${LABEL} created`);
      }
      closeForm();
      refresh();
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ---- Wire up ----------------------------------------------------------------------
  $("new-btn").onclick = () => openForm();
  $("cancel-btn").onclick = closeForm;
  $("overlay").addEventListener("click", (e) => { if (e.target.id === "overlay") closeForm(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("overlay").hidden) closeForm(); });
  $("form").addEventListener("submit", save);
  $("sort").onchange = (e) => { state.sort = e.target.value; refresh(); };
  let debounce;
  $("search").addEventListener("input", (e) => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { state.q = e.target.value; refresh(); }, 250);
  });

  $("list").innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  renderChips();
  refresh();
})();
'''

TEST_STORE = r'''import datetime as dt

from app.models import RecordIn
from app.store import RecordStore


def make(store, name, **kw):
    return store.create(RecordIn(name=name, **kw))


def test_crud_and_timestamps():
    store = RecordStore()
    created = make(store, "First one")
    assert store.get(created.id) == created
    updated = store.update(created.id, RecordIn(name="Renamed", status="confirmed"))
    assert updated.name == "Renamed" and updated.status == "confirmed" and updated.created_at == created.created_at
    assert store.delete(created.id) is True
    assert store.get(created.id) is None
    assert store.update(99, RecordIn(name="x" * 3)) is None and store.delete(99) is False


def test_search_filter_sort_and_stats():
    store = RecordStore()
    make(store, "Alpha trip", description="window seat", status="pending", date=dt.date(2030, 5, 1))
    make(store, "Beta trip", status="completed", date=dt.date(2030, 1, 1))
    make(store, "Gamma", description="aisle", status="pending")
    assert [r.name for r in store.list(q="seat")] == ["Alpha trip"]
    assert {r.name for r in store.list(status="pending")} == {"Alpha trip", "Gamma"}
    assert [r.name for r in store.list(sort="name")] == ["Alpha trip", "Beta trip", "Gamma"]
    assert [r.name for r in store.list(sort="date")][:2] == ["Beta trip", "Alpha trip"]
    assert store.stats() == {"total": 3, "pending": 2, "confirmed": 0, "completed": 1, "cancelled": 0}
'''

TEST_API = r'''from fastapi.testclient import TestClient

from app import main

URL = "/api/__RESOURCES__"


def client() -> TestClient:
    main.store = main.RecordStore()
    return TestClient(main.app)


def test_app_page_and_assets():
    c = client()
    page = c.get("/")
    assert page.status_code == 200 and "__TITLE__" in page.text
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/styles.css").status_code == 200
    assert c.get("/health").json() == {"status": "ok"}


def test_full_crud_over_http():
    c = client()
    created = c.post(URL, json={"name": "First", "description": "hello", "status": "confirmed", "date": "2030-01-02"})
    assert created.status_code == 201
    rid = created.json()["id"]
    assert c.get(f"{URL}/{rid}").json()["date"] == "2030-01-02"
    assert c.put(f"{URL}/{rid}", json={"name": "Renamed", "status": "completed"}).json()["name"] == "Renamed"
    assert c.get(URL, params={"status": "completed"}).json()[0]["id"] == rid
    assert c.get(f"{URL}/stats").json()["completed"] == 1
    assert c.delete(f"{URL}/{rid}").status_code == 204
    assert c.get(f"{URL}/{rid}").status_code == 404
    assert c.delete(f"{URL}/{rid}").status_code == 404


def test_validation_errors():
    c = client()
    assert c.post(URL, json={"name": "x"}).status_code == 422
    assert c.post(URL, json={"name": "Valid", "status": "bogus"}).status_code == 422
    assert c.post(URL, json={"name": "Valid", "date": "not-a-date"}).status_code == 422
    assert c.get(URL, params={"sort": "bogus"}).status_code == 422
'''

README = r'''# __TITLE__

A full-stack web app to manage __RESOURCES_LOWER__, generated by Intent2Deploy AI from the request: "__INTENT__".

## Features

- Interactive dashboard with live counts by status (click a card to filter)
- Search, status filters and sorting
- Create, edit and delete __RESOURCES_LOWER__ in a validated dialog, with instant feedback
- Responsive layout with automatic dark mode
- REST API at `/api/__RESOURCES__` (interactive docs at `/docs`)

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port __PORT__
```

Open http://127.0.0.1:__PORT__ — API docs: http://127.0.0.1:__PORT__/docs

__WHERE_IT_RUNS__

## Test

```bash
python -m pytest -v
```

## Notes

- Data is kept in memory and resets when the server restarts; add a database before production use.
'''


def files(common: dict) -> dict[str, str]:
    return {
        "app/__init__.py": '"""__TITLE__ package."""\n',
        "app/models.py": MODELS_PY,
        "app/store.py": STORE_PY,
        "app/main.py": MAIN_PY,
        "static/index.html": INDEX_HTML,
        "static/styles.css": STYLES_CSS,
        "static/app.js": APP_JS,
        "tests/test_store.py": TEST_STORE,
        "tests/test_api.py": TEST_API,
        "requirements.txt": common["requirements"],
        "pytest.ini": common["pytest_ini"],
        "pyproject.toml": common["pyproject"],
        ".github/workflows/ci.yml": common["ci"],
        "README.md": README,
    }
