"""Add-on: dark mode with a toggle (sign-in pages).

Follows the device's light/dark setting until the person picks one with the
🌙/☀️ button; the choice is remembered in the browser.
"""
from __future__ import annotations

_DARK_VARS = """  --bg: #1c1917;
  --text: #f5f5f4;
  --muted: #a8a29e;
  --line: #44403c;
  --danger: #f87171;
  --success: #4ade80;"""

_DARK_RULES = """.shell { background: #292524; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5); }
input, .password-row .toggle { background: #1c1917; color: var(--text); border-color: var(--line); }
.tabs { border-bottom-color: var(--line); }
.demo-code { background: #422006; border-color: #b45309; color: #fde68a; }
.strength { background: #44403c; }"""


def _scoped(rules: str, scope: str) -> str:
    return "\n".join(f"{scope} {line}" for line in rules.splitlines())


CSS = f"""
/* Dark mode: follows the device setting unless a theme was picked with the toggle. */
:root[data-theme="dark"] {{
{_DARK_VARS}
}}
{_scoped(_DARK_RULES, ':root[data-theme="dark"]')}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{_DARK_VARS}
  }}
{_scoped(_DARK_RULES, '  :root:not([data-theme="light"])')}
}}
.theme-toggle {{
  position: fixed;
  top: 16px;
  right: 16px;
  width: 40px;
  height: 40px;
  border-radius: 20px;
  border: 1px solid var(--line, #d6d3d1);
  background: rgba(255, 255, 255, 0.15);
  font-size: 18px;
  cursor: pointer;
}}
"""

BUTTON = '  <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Switch to dark mode">🌙</button>\n'

JS = r'''
// Dark mode toggle: remembers the choice; otherwise follows the device setting.
(() => {
  const root = document.documentElement;
  const button = document.getElementById("theme-toggle");
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const saved = (() => { try { return localStorage.getItem("theme"); } catch { return null; } })();
  if (saved === "dark" || saved === "light") root.dataset.theme = saved;
  const isDark = () => (root.dataset.theme ? root.dataset.theme === "dark" : media.matches);
  const render = () => {
    button.textContent = isDark() ? "☀️" : "🌙";
    button.setAttribute("aria-label", isDark() ? "Switch to light mode" : "Switch to dark mode");
  };
  button.addEventListener("click", () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("theme", root.dataset.theme); } catch { /* private mode: not remembered */ }
    render();
  });
  media.addEventListener("change", render);
  render();
})();
'''

TEST = r'''from fastapi.testclient import TestClient

from app import main


def test_page_has_a_dark_mode_toggle():
    client = TestClient(main.app)
    assert 'id="theme-toggle"' in client.get("/").text
    css = client.get("/static/styles.css").text
    assert 'data-theme="dark"' in css and "prefers-color-scheme: dark" in css
    assert "theme-toggle" in client.get("/static/app.js").text
'''


def applicable(files: dict[str, str]) -> bool:
    return 'id="auth-form"' in files.get("static/index.html", "") and "static/styles.css" in files \
        and "static/app.js" in files and "<body" in files.get("static/index.html", "")


def applied(files: dict[str, str]) -> bool:
    return 'data-theme="dark"' in files.get("static/styles.css", "") or 'id="theme-toggle"' in files.get("static/index.html", "")


def apply(files: dict[str, str]) -> dict[str, str]:
    html = files["static/index.html"]
    body_end = html.index(">", html.index("<body")) + 1
    return {
        "static/styles.css": files["static/styles.css"].rstrip("\n") + "\n" + CSS,
        "static/index.html": html[:body_end] + "\n" + BUTTON.rstrip("\n") + html[body_end:],
        "static/app.js": files["static/app.js"].rstrip("\n") + "\n" + JS,
        "tests/test_dark_mode.py": TEST,
    }
