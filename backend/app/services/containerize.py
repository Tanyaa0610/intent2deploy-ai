"""Containerization: every project Intent2Deploy delivers ships with a
Dockerfile, a .dockerignore, a docker-compose.yml, a GitHub Actions job that
builds the image and checks the running container, and README instructions.

`detect` recognises the project type from its files (works on a path->content
mapping, so it serves both repositories on disk and freshly generated
projects); `docker_files` renders the files for it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

HOST_PORT = 8010  # host port used in docker-compose.yml / README examples
PRODUCTION_CHECK_PATH = ".github/scripts/production_check.py"
PLATFORM_DOCKER_FILES = {"Dockerfile", ".dockerignore", "docker-compose.yml", ".github/workflows/docker.yml",
                         PRODUCTION_CHECK_PATH}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", "test", ".github", "dist", "build"}
_ASGI_RE = re.compile(r"^(\w+)\s*=\s*FastAPI\(", re.M)
_FLASK_RE = re.compile(r"^(\w+)\s*=\s*Flask\(", re.M)
_HEALTH_RE = re.compile(r"""\.(get|route)\(\s*["']/health["']""")


@dataclass
class ContainerSpec:
    kind: str  # python-asgi | python-flask | node | static
    port: int  # port the app listens on inside the container
    health_path: str
    entry: str = ""  # "module:variable" for Python apps
    install: str = ""  # Python dependency install line
    note: str = ""


def has_dockerfile(files: dict[str, str] | list[str]) -> bool:
    return "Dockerfile" in files


def read_project_files(root: Path, max_bytes: int = 200_000, limit: int = 2000) -> dict[str, str]:
    """Text of the files that matter for detection (skips vendored/test dirs)."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if len(out) >= limit:
            break
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in _SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if p.suffix not in {".py", ".json", ".toml", ".txt", ".html", ".cfg"} and p.name not in {"Dockerfile", "Procfile"}:
            out.setdefault(rel.as_posix(), "")  # presence only
            continue
        try:
            if p.stat().st_size <= max_bytes:
                out[rel.as_posix()] = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return out


def _module_for(path: str) -> str:
    return path[:-3].replace("/", ".")


def _python_install(files: dict[str, str], needs: list[str]) -> str:
    reqs = files.get("requirements.txt")
    if reqs is not None:
        missing = [n for n in needs if n.split("[")[0].lower() not in reqs.lower()]
        line = "RUN pip install --no-cache-dir -r requirements.txt"
        return line + (f" {' '.join(missing)}" if missing else "")
    if "pyproject.toml" in files:
        return f"RUN pip install --no-cache-dir . {' '.join(needs)}"
    return f"RUN pip install --no-cache-dir {' '.join(needs)}"


def detect(files: dict[str, str]) -> ContainerSpec | None:
    """Recognise how to containerize the project, or None if unknown."""
    py_files = {p: c for p, c in files.items() if p.endswith(".py") and p.split("/")[0] not in _SKIP_DIRS}

    def _rank(path: str) -> tuple:
        name = path.rsplit("/", 1)[-1]
        return (name not in ("main.py", "app.py", "server.py", "api.py"), path.count("/"), path)

    has_health = any(_HEALTH_RE.search(c) for c in py_files.values())
    for path in sorted(py_files, key=_rank):
        m = _ASGI_RE.search(py_files[path])
        if m:
            return ContainerSpec(
                "python-asgi", 8000, "/health" if has_health else "/docs", f"{_module_for(path)}:{m.group(1)}",
                _python_install(files, ["uvicorn"]),
            )
    for path in sorted(py_files, key=_rank):
        m = _FLASK_RE.search(py_files[path])
        if m:
            return ContainerSpec(
                "python-flask", 8000, "/health" if has_health else "/", f"{_module_for(path)}:{m.group(1)}",
                _python_install(files, ["flask"]),
            )
    if "package.json" in files:
        try:
            pkg = json.loads(files["package.json"] or "{}")
        except ValueError:
            pkg = {}
        if (pkg.get("scripts") or {}).get("start"):
            return ContainerSpec("node", 3000, "/")
    if "index.html" in files:
        return ContainerSpec("static", 80, "/")
    return None


def _dockerfile(spec: ContainerSpec, files: dict[str, str]) -> str:
    health = (
        f'HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \\\n'
        f'  CMD python -c "import urllib.request; urllib.request.urlopen(\'http://127.0.0.1:{spec.port}{spec.health_path}\', timeout=2)" || exit 1\n'
    )
    if spec.kind in ("python-asgi", "python-flask"):
        copy_reqs = "COPY requirements.txt .\n" if "requirements.txt" in files else ""
        install_first = spec.install if copy_reqs else ""
        cmd = (
            f'CMD ["uvicorn", "{spec.entry}", "--host", "0.0.0.0", "--port", "{spec.port}"]'
            if spec.kind == "python-asgi"
            else f'CMD ["python", "-m", "flask", "--app", "{spec.entry}", "run", "--host", "0.0.0.0", "--port", "{spec.port}"]'
        )
        return (
            "# syntax=docker/dockerfile:1\n"
            "FROM python:3.12-slim\n\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 \\\n    PYTHONUNBUFFERED=1 \\\n    PYTHONPATH=/app\n"
            "WORKDIR /app\n\n"
            "# Dependencies first, so code changes don't reinstall them.\n"
            f"{copy_reqs}{install_first + chr(10) if install_first else ''}"
            "COPY . .\n"
            f"{'' if install_first else spec.install + chr(10)}"
            "\n# Run as an unprivileged user.\n"
            "RUN useradd --create-home --uid 1000 appuser\n"
            "USER appuser\n\n"
            f"EXPOSE {spec.port}\n"
            f"{health}"
            f"{cmd}\n"
        )
    if spec.kind == "node":
        lock = "package-lock.json" in files
        return (
            "# syntax=docker/dockerfile:1\n"
            "FROM node:20-alpine\n"
            "ENV NODE_ENV=production PORT=3000\n"
            "WORKDIR /app\n"
            f"COPY package.json{' package-lock.json' if lock else ''} ./\n"
            f"RUN {'npm ci --omit=dev' if lock else 'npm install --omit=dev'}\n"
            "COPY . .\n"
            "USER node\n"
            "EXPOSE 3000\n"
            'HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1\n'
            'CMD ["npm", "start"]\n'
        )
    return (
        "# syntax=docker/dockerfile:1\n"
        "FROM nginx:1.27-alpine\n"
        "COPY . /usr/share/nginx/html\n"
        "EXPOSE 80\n"
        'HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1\n'
    )


DOCKERIGNORE = """.git
.github
**/__pycache__
**/*.pyc
.pytest_cache
.ruff_cache
.mypy_cache
.venv
venv
node_modules
tests
*.log
.env
.env.*
"""


def _compose(spec: ContainerSpec, service: str, host_port: int = HOST_PORT) -> str:
    return (
        "services:\n"
        f"  {service}:\n"
        "    build: .\n"
        f"    image: {service}:local\n"
        "    ports:\n"
        f'      - "{host_port}:{spec.port}"\n'
        "    restart: unless-stopped\n"
    )


def production_check_script() -> str:
    """Standalone production-check script shipped with every project (CI runs it)."""
    return (Path(__file__).parent / "ci_assets" / "production_check.py").read_text(encoding="utf-8")


def docker_ci_workflow(spec: ContainerSpec, image: str) -> str:
    """GitHub Actions: build the image, run it, and test the running container
    like production (smoke, API, hostile input, load, restart) on every PR and
    on pushes to staging/main (i.e. after each merge). A failure blocks the
    merge gate."""
    return f"""name: Docker

on:
  push:
    branches: [main, staging]
  pull_request:

jobs:
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: docker build -t {image}:${{{{ github.sha }}}} .
      - name: Run container
        run: docker run -d --name app -p {spec.port}:{spec.port} {image}:${{{{ github.sha }}}}
      - name: Check the running container
        run: |
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:{spec.port}{spec.health_path} > /dev/null; then echo "Container is healthy"; exit 0; fi
            sleep 2
          done
          echo "Container did not become healthy"; exit 1
      - name: Production checks (smoke, API, hostile input, load)
        run: python3 {PRODUCTION_CHECK_PATH} http://127.0.0.1:{spec.port} --health {spec.health_path}
      - name: Restart and recovery
        run: |
          docker restart app
          for i in $(seq 1 30); do
            if curl -fsS http://127.0.0.1:{spec.port}{spec.health_path} > /dev/null; then echo "Healthy again after restart"; exit 0; fi
            sleep 2
          done
          echo "Container did not recover after a restart"; exit 1
      - name: Container logs
        if: always()
        run: docker logs app || true
"""


def readme_section(spec: ContainerSpec, image: str, host_port: int = HOST_PORT, preview: bool = False) -> str:
    HOST_PORT = host_port  # noqa: N806 - keeps the template below readable
    where = (
        f"This is the same address Intent2Deploy's staging preview uses for this project (port {host_port}); "
        "stop the preview first if you run the container yourself.\n"
        if preview else ""
    )
    return f"""
## Docker

Build and run the image:

```bash
docker build -t {image} .
docker run --rm -p {HOST_PORT}:{spec.port} {image}
```

Or with Docker Compose:

```bash
docker compose up --build
```

Then open http://127.0.0.1:{HOST_PORT}{"" if spec.health_path in ("/", "/health") else spec.health_path}
(health check: http://127.0.0.1:{HOST_PORT}{spec.health_path}). If port {HOST_PORT} is busy, change
the left side of the port mapping (e.g. `-p 8020:{spec.port}`).
{where}
CI builds this image and checks the running container on every pull request and after each merge
into `staging` and `main` (`.github/workflows/docker.yml`).
"""


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "app"


def docker_files(
    spec: ContainerSpec, files: dict[str, str], project_name: str, host_port: int = HOST_PORT, preview: bool = False
) -> dict[str, str]:
    """Files to add (path -> content). README.md gets a Docker section appended."""
    image = slug(project_name)
    out = {
        "Dockerfile": _dockerfile(spec, files),
        ".dockerignore": DOCKERIGNORE,
        "docker-compose.yml": _compose(spec, image, host_port),
        ".github/workflows/docker.yml": docker_ci_workflow(spec, image),
        PRODUCTION_CHECK_PATH: production_check_script(),
    }
    readme = files.get("README.md")
    section = readme_section(spec, image, host_port, preview)
    if readme is None:
        out["README.md"] = f"# {project_name}\n{section}"
    elif "## Docker" not in readme:
        out["README.md"] = readme.rstrip("\n") + "\n" + section
    return out
