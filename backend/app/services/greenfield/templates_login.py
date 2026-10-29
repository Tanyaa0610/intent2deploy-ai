"""Built-in sign-in template (mock mode): sign in, create account and a full
"forgot password" flow (request a reset code, set a new password), on a
FastAPI backend with salted PBKDF2 hashing, session tokens, tests, CI and
Docker. Requests about password reset open the page on the reset view.

No email service is configured in a generated project, so the reset code is
shown on the page and returned by the API in demo mode (RESET_DEMO_MODE=1,
the default) — the README explains how to send it by email instead.
Placeholders: __TITLE__, __INITIAL__, __INTENT__, __START_MODE__,
__SUBTITLE__, __PORT__, __WHERE_IT_RUNS__ — filled by templates.files().
"""
from __future__ import annotations

import re

RESET_KEYWORDS = re.compile(r"\b(reset|forgot|forgotten|recover|recovery)\b", re.I)


def wants_reset(intent: str) -> bool:
    return bool(RESET_KEYWORDS.search(intent))


def _with_suffix(slug: str, suffix: str) -> str:
    """'food-website' -> 'food-website-login'; 'password-reset' stays as it is."""
    return slug if suffix.split("-")[-1] in slug.split("-") else f"{slug}-{suffix}"


def design(title: str, slug: str, intent: str) -> dict:
    reset = wants_reset(intent)
    focus = "password reset" if reset else "sign-in"
    return {
        "project_name": _with_suffix(slug, "password-reset" if reset else "login"),
        "summary": f"A {title} {focus} experience: interactive sign-in, account creation and a complete "
        "forgot-password flow (reset code, new password), backed by a FastAPI service with salted password "
        "hashing and session tokens.",
        "requirements": [
            "Users can create an account with an email address and password.",
            "Users can sign in with their email and password and receive a session token.",
            "Users who forgot their password can request a reset code and set a new password with it.",
            "Reset codes are single-use, expire after 15 minutes and lock after 5 wrong attempts.",
            "Resetting a password signs out every existing session of that account.",
            "Wrong credentials are rejected without revealing whether the email exists.",
            "The page validates input in the browser before submitting and shows clear feedback.",
        ],
        "non_functional": [
            "Passwords and reset codes are never stored in plain text (PBKDF2-SHA256 / SHA-256).",
            "The page is responsive and usable on mobile widths.",
            "No external services are required to run or test the project.",
        ],
        "acceptance_criteria": [
            "GET / serves the page" + (", opened on the password-reset view." if reset else "."),
            "POST /api/register creates an account; registering the same email twice returns 409.",
            "POST /api/login returns a token for valid credentials and 401 otherwise.",
            "POST /api/password-reset/request always answers the same way, whether or not the email exists.",
            "POST /api/password-reset/confirm sets the new password for a valid code and rejects bad, used or expired codes.",
            "The automated test suite passes.",
        ],
        "stack": "Python 3 · FastAPI · vanilla HTML/CSS/JavaScript · pytest",
        "components": [
            {"name": "Web UI", "responsibility": "Sign-in, sign-up and forgot-password views with client-side validation.",
             "files": ["static/index.html", "static/styles.css", "static/app.js"]},
            {"name": "API", "responsibility": "Serves the page and the account / password-reset endpoints.",
             "files": ["app/__init__.py", "app/main.py"]},
            {"name": "User store", "responsibility": "Accounts, password hashing, sessions and reset codes.",
             "files": ["app/users.py"]},
            {"name": "Tests", "responsibility": "Unit tests for the store and API tests for every endpoint.",
             "files": ["tests/test_users.py", "tests/test_api.py"]},
            {"name": "Project config", "responsibility": "Dependencies, test and lint configuration, docs.",
             "files": ["requirements.txt", "pytest.ini", "pyproject.toml", "README.md"]},
            {"name": "CI pipeline", "responsibility": "GitHub Actions: lint, security scan and tests on every push and PR.",
             "files": [".github/workflows/ci.yml"]},
        ],
        "files": [
            {"path": "app/__init__.py", "purpose": "Package marker."},
            {"path": "app/users.py", "purpose": "In-memory user store: hashing, sessions, reset codes."},
            {"path": "app/main.py", "purpose": "FastAPI app: page, register, login, password reset, /health."},
            {"path": "static/index.html", "purpose": f"{title} sign-in / sign-up / reset page."},
            {"path": "static/styles.css", "purpose": "Responsive styling for the page."},
            {"path": "static/app.js", "purpose": "Views, validation, password toggle, API calls, feedback."},
            {"path": "tests/test_users.py", "purpose": "User store tests."},
            {"path": "tests/test_api.py", "purpose": "Endpoint tests."},
            {"path": "requirements.txt", "purpose": "Runtime and test dependencies."},
            {"path": "pytest.ini", "purpose": "Test discovery configuration."},
            {"path": "pyproject.toml", "purpose": "Ruff lint configuration."},
            {"path": "README.md", "purpose": "How to run and test the project."},
            {"path": ".github/workflows/ci.yml", "purpose": "GitHub Actions CI: ruff, security scan, pytest."},
        ],
        "dependencies": ["fastapi", "uvicorn", "httpx (tests)", "pytest (tests)"],
        "test_command": "python3 -m pytest -q",
        "run_command": "uvicorn app.main:app --reload --port __PORT__",
        "risks": [
            "Accounts are kept in memory and are lost on restart; a database is needed before production use.",
            "Reset codes are shown on screen in demo mode; connect an email service before real users rely on it.",
        ],
        "template": "login_web_app",
    }


USERS_PY = r'''"""In-memory user accounts: salted PBKDF2 password hashing, sessions and
single-use password-reset codes."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8
RESET_CODE_TTL_SECONDS = 15 * 60
RESET_MAX_ATTEMPTS = 5
_ITERATIONS = 200_000


class AccountExistsError(Exception):
    pass


class InvalidAccountError(ValueError):
    pass


class InvalidResetCodeError(ValueError):
    pass


@dataclass
class User:
    email: str
    salt: bytes
    password_hash: bytes


@dataclass
class ResetCode:
    code_hash: str
    expires_at: float
    attempts: int = 0


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)


def _code_hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class UserStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._sessions: dict[str, str] = {}
        self._resets: dict[str, ResetCode] = {}

    @staticmethod
    def normalize(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _check_password(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidAccountError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    def register(self, email: str, password: str) -> User:
        email = self.normalize(email)
        if not EMAIL_RE.match(email):
            raise InvalidAccountError("Enter a valid email address.")
        self._check_password(password)
        if email in self._users:
            raise AccountExistsError("An account with this email already exists.")
        salt = secrets.token_bytes(16)
        user = User(email=email, salt=salt, password_hash=_hash(password, salt))
        self._users[email] = user
        return user

    def authenticate(self, email: str, password: str) -> str | None:
        """Return a new session token, or None if the credentials are wrong."""
        user = self._users.get(self.normalize(email))
        if user is None:
            # Hash anyway so response time does not reveal whether the email exists.
            _hash(password, secrets.token_bytes(16))
            return None
        if not hmac.compare_digest(_hash(password, user.salt), user.password_hash):
            return None
        token = secrets.token_urlsafe(32)
        self._sessions[token] = user.email
        return token

    def user_for_token(self, token: str) -> str | None:
        return self._sessions.get(token)

    # -- password reset ------------------------------------------------------
    def request_reset(self, email: str, now: float | None = None) -> str | None:
        """A new 6-digit reset code for the account, or None if there is no such
        account. Callers must answer the same way in both cases."""
        email = self.normalize(email)
        if email not in self._users:
            return None
        code = f"{secrets.randbelow(1_000_000):06d}"
        self._resets[email] = ResetCode(_code_hash(code), (now or time.time()) + RESET_CODE_TTL_SECONDS)
        return code

    def reset_password(self, email: str, code: str, new_password: str, now: float | None = None) -> None:
        email = self.normalize(email)
        self._check_password(new_password)
        pending = self._resets.get(email)
        if pending is None or (now or time.time()) > pending.expires_at or pending.attempts >= RESET_MAX_ATTEMPTS:
            self._resets.pop(email, None)
            raise InvalidResetCodeError("This reset code is invalid or has expired. Request a new one.")
        if not hmac.compare_digest(pending.code_hash, _code_hash(code.strip())):
            pending.attempts += 1
            raise InvalidResetCodeError("That code is not correct.")
        user = self._users[email]
        user.salt = secrets.token_bytes(16)
        user.password_hash = _hash(new_password, user.salt)
        del self._resets[email]  # single use
        # Sign out everywhere: a reset usually means the old password is compromised.
        self._sessions = {t: e for t, e in self._sessions.items() if e != email}
'''

MAIN_PY = r'''"""__TITLE__: sign in, create account, reset password."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.users import AccountExistsError, InvalidAccountError, InvalidResetCodeError, UserStore

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
# No email service is configured, so in demo mode the reset code is returned
# to the page. Set RESET_DEMO_MODE=0 once codes are sent by email.
DEMO_MODE = os.environ.get("RESET_DEMO_MODE", "1") == "1"
RESET_SENT = "If an account exists for that email, a reset code has been sent."

app = FastAPI(title="__TITLE__")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
store = UserStore()


class Credentials(BaseModel):
    email: str
    password: str


class ResetRequest(BaseModel):
    email: str


class ResetConfirm(BaseModel):
    email: str
    code: str
    new_password: str


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/register", status_code=201)
def register(body: Credentials) -> dict:
    try:
        user = store.register(body.email, body.password)
    except AccountExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidAccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"email": user.email}


@app.post("/api/login")
def login(body: Credentials) -> dict:
    token = store.authenticate(body.email, body.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    return {"token": token, "email": store.normalize(body.email)}


@app.get("/api/me")
def me(authorization: str = Header(default="")) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    email = store.user_for_token(token) if token else None
    if email is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return {"email": email}


@app.post("/api/password-reset/request")
def request_reset(body: ResetRequest) -> dict:
    code = store.request_reset(body.email)
    answer = {"message": RESET_SENT, "demo_mode": DEMO_MODE}
    if DEMO_MODE and code is not None:
        answer["demo_code"] = code
    return answer


@app.post("/api/password-reset/confirm")
def confirm_reset(body: ResetConfirm) -> dict:
    try:
        store.reset_password(body.email, body.code, body.new_password)
    except InvalidAccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except InvalidResetCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "Your password has been reset. You can sign in with the new password."}
'''

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <link rel="stylesheet" href="/static/styles.css" />
</head>
<body data-start-mode="__START_MODE__">
  <main class="shell">
    <section class="brand">
      <div class="logo" aria-hidden="true">__INITIAL__</div>
      <h1>__TITLE__</h1>
      <p id="brand-subtitle">__SUBTITLE__</p>
    </section>

    <section class="panel">
      <div class="tabs" role="tablist">
        <button type="button" class="tab" data-mode="login" role="tab">Sign in</button>
        <button type="button" class="tab" data-mode="register" role="tab">Create account</button>
      </div>

      <!-- Sign in / create account -->
      <form id="auth-form" novalidate>
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="email" required />
        <p class="field-error" data-for="email"></p>

        <label for="password">Password</label>
        <div class="password-row">
          <input id="password" name="password" type="password" autocomplete="current-password" minlength="8" required />
          <button type="button" class="toggle" data-target="password" aria-label="Show password">Show</button>
        </div>
        <p class="field-error" data-for="password"></p>
        <button type="button" class="link" id="forgot-link">Forgot password?</button>

        <button type="submit" class="primary" id="submit">Sign in</button>
      </form>

      <!-- Forgot password: step 1, ask for a code -->
      <form id="reset-request-form" novalidate hidden>
        <h2>Reset your password</h2>
        <p class="hint">Enter the email you signed up with and we'll send you a 6-digit reset code.</p>
        <label for="reset-email">Email</label>
        <input id="reset-email" type="email" autocomplete="email" required />
        <p class="field-error" data-for="reset-email"></p>
        <button type="submit" class="primary" id="reset-request-submit">Send reset code</button>
        <button type="button" class="link back-to-login">← Back to sign in</button>
      </form>

      <!-- Forgot password: step 2, set the new password -->
      <form id="reset-confirm-form" novalidate hidden>
        <h2>Choose a new password</h2>
        <p class="hint" id="reset-sent-to"></p>
        <div class="demo-code" id="demo-code" hidden></div>
        <label for="reset-code">Reset code</label>
        <input id="reset-code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" required />
        <p class="field-error" data-for="reset-code"></p>
        <label for="new-password">New password</label>
        <div class="password-row">
          <input id="new-password" type="password" autocomplete="new-password" minlength="8" required />
          <button type="button" class="toggle" data-target="new-password" aria-label="Show password">Show</button>
        </div>
        <div class="strength" aria-hidden="true"><span id="strength-bar"></span></div>
        <p class="field-error" data-for="new-password"></p>
        <label for="confirm-password">Confirm new password</label>
        <input id="confirm-password" type="password" autocomplete="new-password" required />
        <p class="field-error" data-for="confirm-password"></p>
        <button type="submit" class="primary" id="reset-confirm-submit">Reset password</button>
        <button type="button" class="link" id="resend-link">Didn't get a code? Send a new one</button>
        <button type="button" class="link back-to-login">← Back to sign in</button>
      </form>

      <p id="message" role="status"></p>
    </section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
'''

STYLES_CSS = r''':root {
  --accent: #c2410c;
  --accent-dark: #9a3412;
  --bg: #fff7ed;
  --text: #1c1917;
  --muted: #78716c;
  --line: #d6d3d1;
  --danger: #b91c1c;
  --success: #15803d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
  display: grid;
  place-items: center;
}
.shell {
  width: min(920px, 100% - 32px);
  display: grid;
  grid-template-columns: 1fr 1fr;
  background: #fff;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(28, 25, 23, 0.12);
}
.brand {
  background: linear-gradient(160deg, var(--accent), var(--accent-dark));
  color: #fff;
  padding: 48px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.logo {
  width: 56px; height: 56px; border-radius: 14px; background: rgba(255, 255, 255, 0.2);
  display: grid; place-items: center; font-size: 28px; font-weight: 700;
}
.brand h1 { margin: 20px 0 8px; font-size: 32px; }
.brand p { margin: 0; opacity: 0.9; }
.panel { padding: 40px; }
.panel h2 { margin: 0 0 6px; font-size: 20px; }
.hint { color: var(--muted); font-size: 14px; margin: 0 0 8px; }
.tabs { display: flex; gap: 4px; margin-bottom: 24px; border-bottom: 1px solid #e7e5e4; }
.tab {
  border: none; background: none; padding: 10px 14px; font: inherit; font-weight: 600;
  color: var(--muted); border-bottom: 2px solid transparent; cursor: pointer;
}
.tab.active { color: var(--accent); border-bottom-color: var(--accent); }
.tabs.hidden { visibility: hidden; height: 0; margin: 0; overflow: hidden; }
label { display: block; font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
input { width: 100%; padding: 11px 12px; border: 1px solid var(--line); border-radius: 8px; font: inherit; }
input:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
input[aria-invalid="true"] { border-color: var(--danger); }
#reset-code { letter-spacing: 6px; font-size: 20px; text-align: center; }
.password-row { display: flex; gap: 8px; }
.password-row .toggle { border: 1px solid var(--line); background: #fff; border-radius: 8px; padding: 0 14px; cursor: pointer; }
.field-error { color: var(--danger); font-size: 13px; min-height: 18px; margin: 4px 0 0; }
.link { border: none; background: none; padding: 4px 0; color: var(--accent); font: inherit; font-size: 14px; cursor: pointer; display: block; }
.link:hover { text-decoration: underline; }
.primary {
  width: 100%; margin-top: 18px; padding: 12px; border: none; border-radius: 8px;
  background: var(--accent); color: #fff; font: inherit; font-weight: 600; cursor: pointer;
}
.primary:hover { background: var(--accent-dark); }
.primary:disabled { opacity: 0.6; cursor: wait; }
.strength { height: 4px; background: #e7e5e4; border-radius: 2px; margin-top: 6px; overflow: hidden; }
.strength span { display: block; height: 100%; width: 0; transition: width .2s, background .2s; }
.demo-code { background: #fef3c7; border: 1px dashed #d97706; border-radius: 8px; padding: 10px 12px; font-size: 14px; margin: 6px 0; }
.demo-code strong { letter-spacing: 3px; font-size: 18px; }
#message { min-height: 20px; margin: 14px 0 0; font-size: 14px; }
#message.error { color: var(--danger); }
#message.success { color: var(--success); }
@media (max-width: 720px) {
  .shell { grid-template-columns: 1fr; }
  .brand { padding: 32px 24px; }
  .panel { padding: 28px 24px; }
}
'''

APP_JS = r'''(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const forms = { auth: $("auth-form"), request: $("reset-request-form"), confirm: $("reset-confirm-form") };
  const tabs = document.querySelectorAll(".tab");
  const message = $("message");
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
  let mode = "login";
  let resetEmail = "";

  function show(text, kind = "") {
    message.textContent = text;
    message.className = kind;
  }

  function setError(field, text) {
    document.querySelector(`.field-error[data-for="${field.id}"]`).textContent = text;
    field.setAttribute("aria-invalid", text ? "true" : "false");
  }

  function checkEmail(field) {
    const ok = EMAIL.test(field.value.trim());
    setError(field, ok ? "" : "Enter a valid email address.");
    return ok;
  }

  function checkLength(field, label = "Password") {
    const ok = field.value.length >= 8;
    setError(field, ok ? "" : `${label} must be at least 8 characters.`);
    return ok;
  }

  async function post(url, body) {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong.");
    return data;
  }

  // ---- Views ----------------------------------------------------------------
  function setView(view) {
    mode = view;
    forms.auth.hidden = !(view === "login" || view === "register");
    forms.request.hidden = view !== "reset";
    forms.confirm.hidden = view !== "reset-confirm";
    document.querySelector(".tabs").classList.toggle("hidden", forms.auth.hidden);
    tabs.forEach((t) => {
      t.classList.toggle("active", t.dataset.mode === view);
      t.setAttribute("aria-selected", String(t.dataset.mode === view));
    });
    $("submit").textContent = view === "register" ? "Create account" : "Sign in";
    $("password").autocomplete = view === "register" ? "new-password" : "current-password";
    $("forgot-link").hidden = view !== "login";
    $("brand-subtitle").textContent =
      view === "register" ? "Create your account." : view.startsWith("reset") ? "Reset your password." : "Sign in to continue.";
    show("");
  }

  tabs.forEach((tab) => tab.addEventListener("click", () => setView(tab.dataset.mode)));
  $("forgot-link").addEventListener("click", () => {
    $("reset-email").value = $("email").value;
    setView("reset");
    $("reset-email").focus();
  });
  document.querySelectorAll(".back-to-login").forEach((b) => b.addEventListener("click", () => setView("login")));

  document.querySelectorAll(".toggle").forEach((button) =>
    button.addEventListener("click", () => {
      const field = $(button.dataset.target);
      const hidden = field.type === "password";
      field.type = hidden ? "text" : "password";
      button.textContent = hidden ? "Hide" : "Show";
      button.setAttribute("aria-label", hidden ? "Hide password" : "Show password");
    })
  );

  // ---- Sign in / create account -----------------------------------------------
  forms.auth.addEventListener("submit", async (event) => {
    event.preventDefault();
    const ok = [checkEmail($("email")), checkLength($("password"))].every(Boolean);
    if (!ok) return;
    const button = $("submit");
    button.disabled = true;
    show(mode === "login" ? "Signing in…" : "Creating account…");
    try {
      const body = { email: $("email").value.trim(), password: $("password").value };
      if (mode === "login") {
        const data = await post("/api/login", body);
        sessionStorage.setItem("token", data.token);
        show(`Welcome back, ${data.email}!`, "success");
      } else {
        await post("/api/register", body);
        setView("login");
        show("Account created. You can sign in now.", "success");
      }
    } catch (e) {
      show(e.message || "Could not reach the server. Check your connection.", "error");
    } finally {
      button.disabled = false;
    }
  });

  // ---- Forgot password ------------------------------------------------------------
  async function sendCode() {
    const data = await post("/api/password-reset/request", { email: resetEmail });
    $("reset-sent-to").textContent = `${data.message} Enter it below for ${resetEmail}.`;
    const demo = $("demo-code");
    demo.hidden = !data.demo_code;
    if (data.demo_code) {
      demo.innerHTML = `Demo mode (no email service configured): your code is <strong>${data.demo_code}</strong>`;
    }
  }

  forms.request.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!checkEmail($("reset-email"))) return;
    const button = $("reset-request-submit");
    button.disabled = true;
    try {
      resetEmail = $("reset-email").value.trim();
      await sendCode();
      setView("reset-confirm");
      $("reset-code").focus();
    } catch (e) {
      show(e.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("resend-link").addEventListener("click", async () => {
    try {
      await sendCode();
      show("A new code has been sent.", "success");
    } catch (e) {
      show(e.message, "error");
    }
  });

  $("new-password").addEventListener("input", (e) => {
    const v = e.target.value;
    const score = [v.length >= 8, v.length >= 12, /[A-Z]/.test(v) && /[a-z]/.test(v), /\d/.test(v), /[^\w\s]/.test(v)]
      .filter(Boolean).length;
    const bar = $("strength-bar");
    bar.style.width = `${score * 20}%`;
    bar.style.background = score < 3 ? "#dc2626" : score < 4 ? "#d97706" : "#16a34a";
  });

  forms.confirm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = $("reset-code");
    const codeOk = /^\d{6}$/.test(code.value.trim());
    setError(code, codeOk ? "" : "Enter the 6-digit code.");
    const lengthOk = checkLength($("new-password"), "New password");
    const match = $("new-password").value === $("confirm-password").value;
    setError($("confirm-password"), match ? "" : "Passwords do not match.");
    if (!(codeOk && lengthOk && match)) return;
    const button = $("reset-confirm-submit");
    button.disabled = true;
    try {
      const data = await post("/api/password-reset/confirm", {
        email: resetEmail, code: code.value.trim(), new_password: $("new-password").value,
      });
      $("email").value = resetEmail;
      $("password").value = "";
      [code, $("new-password"), $("confirm-password")].forEach((f) => (f.value = ""));
      setView("login");
      show(data.message, "success");
    } catch (e) {
      show(e.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  setView(document.body.dataset.startMode === "reset" ? "reset" : "login");
})();
'''

TEST_USERS = r'''import pytest

from app.users import AccountExistsError, InvalidAccountError, InvalidResetCodeError, UserStore


def test_register_and_authenticate():
    store = UserStore()
    store.register("Ana@Example.com", "correct-horse")
    token = store.authenticate("ana@example.com", "correct-horse")
    assert token
    assert store.user_for_token(token) == "ana@example.com"


def test_wrong_password_and_unknown_email_rejected():
    store = UserStore()
    store.register("ana@example.com", "correct-horse")
    assert store.authenticate("ana@example.com", "wrong-password") is None
    assert store.authenticate("nobody@example.com", "correct-horse") is None


def test_password_is_not_stored_in_plain_text():
    store = UserStore()
    user = store.register("ana@example.com", "correct-horse")
    assert b"correct-horse" not in user.password_hash


def test_duplicate_and_invalid_registrations_rejected():
    store = UserStore()
    store.register("ana@example.com", "correct-horse")
    with pytest.raises(AccountExistsError):
        store.register("ANA@example.com", "another-password")
    with pytest.raises(InvalidAccountError):
        store.register("not-an-email", "correct-horse")
    with pytest.raises(InvalidAccountError):
        store.register("bo@example.com", "short")


def test_password_reset_flow():
    store = UserStore()
    store.register("ana@example.com", "correct-horse")
    old_session = store.authenticate("ana@example.com", "correct-horse")
    code = store.request_reset("ANA@example.com")
    assert code and len(code) == 6 and code.isdigit()
    store.reset_password("ana@example.com", code, "brand-new-pass")
    assert store.authenticate("ana@example.com", "correct-horse") is None
    assert store.authenticate("ana@example.com", "brand-new-pass")
    assert store.user_for_token(old_session) is None  # signed out everywhere
    with pytest.raises(InvalidResetCodeError):
        store.reset_password("ana@example.com", code, "another-pass1")  # single use


def test_reset_for_unknown_email_gives_no_code():
    assert UserStore().request_reset("nobody@example.com") is None


def test_reset_code_expires_and_locks_after_wrong_attempts():
    store = UserStore()
    store.register("ana@example.com", "correct-horse")
    code = store.request_reset("ana@example.com", now=1000.0)
    with pytest.raises(InvalidResetCodeError):
        store.reset_password("ana@example.com", code, "brand-new-pass", now=1000.0 + 16 * 60)
    code = store.request_reset("ana@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        with pytest.raises(InvalidResetCodeError):
            store.reset_password("ana@example.com", wrong, "brand-new-pass")
    with pytest.raises(InvalidResetCodeError):
        store.reset_password("ana@example.com", code, "brand-new-pass")  # locked after 5 wrong tries


def test_reset_rejects_short_new_password():
    store = UserStore()
    store.register("ana@example.com", "correct-horse")
    code = store.request_reset("ana@example.com")
    with pytest.raises(InvalidAccountError):
        store.reset_password("ana@example.com", code, "short")
'''

TEST_API = r'''from fastapi.testclient import TestClient

from app import main


def client() -> TestClient:
    main.store = main.UserStore()
    return TestClient(main.app)


def test_page_served_with_every_view():
    resp = client().get("/")
    assert resp.status_code == 200
    assert "__TITLE__" in resp.text
    for view in ("auth-form", "reset-request-form", "reset-confirm-form", "Forgot password?"):
        assert view in resp.text


def test_static_assets_served():
    c = client()
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/styles.css").status_code == 200


def test_register_then_login_then_me():
    c = client()
    assert c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"}).status_code == 201
    resp = c.post("/api/login", json={"email": "ana@example.com", "password": "correct-horse"})
    assert resp.status_code == 200
    token = resp.json()["token"]
    me = c.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json() == {"email": "ana@example.com"}


def test_bad_credentials_and_duplicates():
    c = client()
    c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"})
    assert c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"}).status_code == 409
    assert c.post("/api/login", json={"email": "ana@example.com", "password": "nope-nope"}).status_code == 401
    assert c.post("/api/register", json={"email": "bad", "password": "correct-horse"}).status_code == 422
    assert c.get("/api/me").status_code == 401


def test_password_reset_over_http():
    c = client()
    c.post("/api/register", json={"email": "ana@example.com", "password": "correct-horse"})
    sent = c.post("/api/password-reset/request", json={"email": "ana@example.com"}).json()
    unknown = c.post("/api/password-reset/request", json={"email": "nobody@example.com"}).json()
    assert sent["message"] == unknown["message"]  # does not reveal which emails have accounts
    assert "demo_code" not in unknown
    bad = c.post("/api/password-reset/confirm",
                 json={"email": "ana@example.com", "code": "x", "new_password": "brand-new-pass"})
    assert bad.status_code == 400
    ok = c.post("/api/password-reset/confirm",
                json={"email": "ana@example.com", "code": sent["demo_code"], "new_password": "brand-new-pass"})
    assert ok.status_code == 200
    assert c.post("/api/login", json={"email": "ana@example.com", "password": "brand-new-pass"}).status_code == 200
    assert c.post("/api/login", json={"email": "ana@example.com", "password": "correct-horse"}).status_code == 401


def test_health():
    assert client().get("/health").json() == {"status": "ok"}
'''

README = r'''# __TITLE__

Sign-in, account creation and a complete forgot-password flow, with a FastAPI backend.

Generated by Intent2Deploy AI from the request: "__INTENT__".

## Features

- Sign in and create an account, with validation as you type
- **Forgot password?** → request a 6-digit reset code → choose a new password (with a strength meter)
- Reset codes are single-use, expire after 15 minutes and lock after 5 wrong attempts
- Resetting a password signs the account out everywhere
- The API never reveals whether an email has an account

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port __PORT__
```

Open http://127.0.0.1:__PORT__.

__WHERE_IT_RUNS__

## Test

```bash
python -m pytest -q
```

## Password reset emails

No email service is configured, so the app runs in **demo mode**: the reset code is shown on the page.
To send codes by email instead, deliver the code returned by `store.request_reset()` with your email
provider in `app/main.py` and start the app with `RESET_DEMO_MODE=0`.

## Notes

- Passwords are hashed with PBKDF2-SHA256 and a per-user salt; reset codes are stored only as SHA-256 hashes.
- Accounts, sessions and reset codes are kept in memory; add a database before production use.
'''


def files(common: dict) -> dict[str, str]:
    return {
        "app/__init__.py": '"""__TITLE__ package."""\n',
        "app/users.py": USERS_PY,
        "app/main.py": MAIN_PY,
        "static/index.html": INDEX_HTML,
        "static/styles.css": STYLES_CSS,
        "static/app.js": APP_JS,
        "tests/test_users.py": TEST_USERS,
        "tests/test_api.py": TEST_API,
        "requirements.txt": common["requirements"],
        "pytest.ini": common["pytest_ini"],
        "pyproject.toml": common["pyproject"],
        ".github/workflows/ci.yml": common["ci"],
        "README.md": README,
    }


def placeholders(intent: str) -> dict[str, str]:
    reset = wants_reset(intent)
    return {"__START_MODE__": "reset" if reset else "login",
            "__SUBTITLE__": "Reset your password." if reset else "Sign in to continue."}
