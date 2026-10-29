"""Built-in project templates used by the mock provider (LLM_MODE=mock).

Mock mode has no model to write arbitrary code, so greenfield generation
picks the closest of a small set of complete, tested project templates and
personalises names/titles from the intent. Every template is a working
project: its own test suite passes and it is clean under the validation
pipeline's ruff lint and security checks. The design it returns says which
template was used, so the UI never presents template output as bespoke AI
generation. LLM_MODE=live generates intent-specific projects instead.
"""
from __future__ import annotations

import re

LOGIN_KEYWORDS = re.compile(r"\b(log ?in|sign ?in|sign ?up|auth\w*|register|registration|account|password)\b", re.I)


# "... and it should be named Acme Trips" / "called X" / "name it X" / "name as X" at the end of a request.
_NAME_CLAUSE = re.compile(
    r"[,;]?\s*(?:\band\s+)?(?:(?:it|the\s+\w+)\s+)?(?:(?:should|must|will|shall|can)\s+)?(?:be\s+)?"
    r"\b(?:named|called|titled|name\s+it(?:\s+as)?|name\s+as)\s+[\"'\u201c]?(?P<name>[^\"'\u201d.,;!]{2,40}?)[\"'\u201d]?\s*[.!]?\s*$",
    re.I,
)


REVISION_MARKER = "Fix requested after testing on staging:"


def _clean(intent: str) -> str:
    # A revision's fix note must not rename the app; only the original request names it.
    intent = intent.split(REVISION_MARKER)[0]
    return re.sub(r"[*_`#>]", "", intent).strip()  # no markdown in names/titles


def _title_case(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in text.split())


def brand_from_intent(intent: str) -> str:
    """'... for flight booking and should name as vanshita flight service' -> 'Vanshita Flight Service'."""
    match = _NAME_CLAUSE.search(_clean(intent))
    return _title_case(match.group("name").strip()) if match else ""


def app_title(intent: str) -> str:
    """The app's display name: the name the user gave it, else its subject."""
    return brand_from_intent(intent) or subject_from_intent(intent)


def subject_from_intent(intent: str) -> str:
    """'Make a login page for a food website' -> 'Food Website'."""
    text = _NAME_CLAUSE.sub("", _clean(intent)).strip()
    text = re.split(r"\s*[.!?]\s+", text, maxsplit=1)[0].strip().rstrip(".!?")
    # "...app like Zomato with login" -> "...app": comparisons and add-ons aren't part of the name.
    text = re.split(r"\s+(?:like|similar to|such as|with|using|that|which)\b", text, maxsplit=1, flags=re.I)[0]
    match = re.search(r"\bfor (?:an? |the |my |our )?([A-Za-z0-9][\w\s'-]{1,40})$", text, re.I)
    if match:
        subject = match.group(1)
    else:
        words = re.sub(r"(?i)^(please\s+)?(make|create|build|generate|write|add|develop)\s+(an?\s+|the\s+)?", "", text).split()
        subject = " ".join(words[:4]) or "New Project"
    return _title_case(subject)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


_GENERIC_WORDS = {"website", "site", "web", "app", "application", "service", "api", "rest", "system", "platform",
                  "managing", "manage", "management", "tracking", "tracker", "simple", "small", "new", "my", "our",
                  "online", "portal", "dashboard", "page", "tool", "full", "stack", "interactive"}


def resource_from(title: str) -> str:
    """'Managing Books' -> 'book'; 'Todo App' -> 'todo'. Used for API route names."""
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in _GENERIC_WORDS]
    word = words[-1] if words else "item"
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def plural(word: str) -> str:
    """delivery -> deliveries, box -> boxes, book -> books."""
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def pick_template(intent: str) -> str:
    from app.services.greenfield.templates_food import FOOD_KEYWORDS

    food = re.search(FOOD_KEYWORDS, intent, re.I)
    login = LOGIN_KEYWORDS.search(intent)
    # "a login page for a food website" asks for a page; "a food delivery app (with login)" asks for the app.
    if login and (not food or re.search(r"\bpage\b", intent, re.I)):
        return "login_web_app"
    if food:
        return "food_delivery_app"
    return "login_web_app" if login else "web_app"


# ---------------------------------------------------------------------------
# Design (requirements + architecture)
# ---------------------------------------------------------------------------
def design(intent: str, port: int = 8010, preview: bool = False) -> dict:
    """Template design for `intent`, always including the Docker setup.
    `port` is where the project runs (its staging-preview port when it has one)."""
    data = with_docker(_design(intent))
    data["port"], data["preview"] = port, preview
    data["run_command"] = data["run_command"].replace("__PORT__", str(port))
    return data


def where_it_runs(port: int, preview: bool) -> str:
    """README sentence saying where the project actually runs."""
    if preview:
        return (
            f"**Where it runs:** http://127.0.0.1:{port} — Intent2Deploy's staging preview serves this project on "
            f"port {port} (this project's own port), and the commands here use the same address. If you run it "
            "yourself while the preview is running, stop the preview first or use another port (e.g. `--port 8020`)."
        )
    return (
        f"**Where it runs:** http://127.0.0.1:{port} once started with the command above. If port {port} is "
        "already in use, pick another one (e.g. `--port 8020`) and open that port instead."
    )


def _design(intent: str) -> dict:
    title = app_title(intent)
    template = pick_template(intent)
    if template == "food_delivery_app":
        from app.services.greenfield import templates_food

        return templates_food.design(title)
    if template == "login_web_app":
        from app.services.greenfield import templates_login

        return templates_login.design(title, slugify(title), intent)
    from app.services.greenfield import templates_webapp

    resource = resource_from(subject_from_intent(intent))
    data = templates_webapp.design(title, resource, plural(resource))
    data["project_name"] = slugify(title) if brand_from_intent(intent) else slugify(title) + "-app"
    return data


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
_COMMON_PYTEST_INI = """[pytest]
pythonpath = .
testpaths = tests
"""

_COMMON_PYPROJECT = """[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E", "F", "W"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "S105", "S106"]
"""

# Runs the same checks as Intent2Deploy's local validation, on GitHub.
_COMMON_CI_WORKFLOW = """name: CI

on:
  push:
    branches: [main, staging]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements.txt ruff
      - name: Lint
        run: ruff check .
      - name: Security scan
        run: ruff check --select S .
      - name: Tests
        run: python -m pytest -v
"""

_COMMON_REQUIREMENTS = """fastapi>=0.110
uvicorn>=0.29
httpx>=0.27
pytest>=8
"""

def files(intent: str, design_data: dict) -> list[dict]:
    """Render the template chosen in `design_data` into project files."""
    title = app_title(intent)
    safe_intent = intent.split(REVISION_MARKER)[0].strip().replace('"', "'")  # the original request
    resource = resource_from(subject_from_intent(intent))
    resources = plural(resource)
    label = resource.replace("-", " ").title()

    def fill(text: str) -> str:
        return (
            text.replace("__TITLE__", title)
            .replace("__INITIAL__", title[:1].upper())
            .replace("__INTENT__", safe_intent)
            .replace("__RESOURCES_LABEL__", resources.replace("-", " ").title())
            .replace("__RESOURCES_LOWER__", resources.replace("-", " "))
            .replace("__RESOURCE_LABEL__", label)
            .replace("__RESOURCES__", resources)
            .replace("__RESOURCE__", resource)
        )

    common = {
        "requirements": _COMMON_REQUIREMENTS, "pytest_ini": _COMMON_PYTEST_INI,
        "pyproject": _COMMON_PYPROJECT, "ci": _COMMON_CI_WORKFLOW,
    }

    if design_data.get("template") == "food_delivery_app":
        from app.services.greenfield import templates_food

        contents = templates_food.files(title, intent, common)
    elif design_data.get("template") == "login_web_app":
        from app.services.greenfield import templates_login

        contents = templates_login.files(common)
        for marker, value in templates_login.placeholders(intent).items():
            contents = {p: c.replace(marker, value) for p, c in contents.items()}
    else:
        from app.services.greenfield import templates_webapp

        contents = templates_webapp.files(common)
    port = int(design_data.get("port") or 8010)
    preview = bool(design_data.get("preview"))
    contents = {p: c.replace("__WHERE_IT_RUNS__", where_it_runs(port, preview)).replace("__PORT__", str(port))
                for p, c in contents.items()}
    contents.update(_docker_files(contents, design_data.get("project_name") or title, port, preview))
    return [{"path": p, "content": fill(c)} for p, c in contents.items()]


# All built-in templates are FastAPI apps at app.main:app with a /health endpoint.
def _template_spec():
    from app.services.containerize import ContainerSpec

    return ContainerSpec("python-asgi", 8000, "/health", "app.main:app", "RUN pip install --no-cache-dir -r requirements.txt")


def _docker_files(contents: dict[str, str], project_name: str, port: int = 8010, preview: bool = False) -> dict[str, str]:
    from app.services.containerize import docker_files

    return docker_files(_template_spec(), contents, project_name, host_port=port, preview=preview)


DOCKER_FILE_SPECS = [
    {"path": "Dockerfile", "purpose": "Container image: Python 3.12 slim, non-root user, health check."},
    {"path": ".dockerignore", "purpose": "Keeps tests, caches and VCS data out of the image."},
    {"path": "docker-compose.yml", "purpose": "One-command local run with Docker Compose."},
    {"path": ".github/workflows/docker.yml",
     "purpose": "CI: build the image, run it and test it like production (smoke, API, hostile input, load, restart)."},
    {"path": ".github/scripts/production_check.py", "purpose": "Production checks CI runs against the running container."},
]
DOCKER_COMPONENT = {
    "name": "Container",
    "responsibility": "Dockerfile, Compose file and CI job that builds the image and tests the running container.",
    "files": [f["path"] for f in DOCKER_FILE_SPECS],
}


def with_docker(design_data: dict) -> dict:
    """Add the Docker files to a template design (idempotent)."""
    paths = {f["path"] for f in design_data["files"]}
    design_data["files"] += [f for f in DOCKER_FILE_SPECS if f["path"] not in paths]
    if not any(c["name"] == "Container" for c in design_data["components"]):
        design_data["components"].append(dict(DOCKER_COMPONENT))
    design_data["stack"] = design_data["stack"] + " · Docker" if "Docker" not in design_data["stack"] else design_data["stack"]
    return design_data
