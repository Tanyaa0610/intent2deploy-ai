"""Architecture analysis (Part B, "Architecture" section).

Deterministic, filesystem-derived — never invented. Walks the target
repository's `src/` (or top-level package) tree and reports the component
list, per-component file/function counts, detected external dependencies,
and a lightweight reverse-import graph used by the blast-radius guardrail.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

EXTERNAL_DEPENDENCY_SIGNALS = {
    "payment_provider": r"PaymentProviderClient",
    "http_client": r"\brequests\.|httpx\.",
    "database": r"sqlite3|sqlalchemy|create_engine",
    "cache": r"\bcache\b",
    "queue": r"\bqueue\b",
}


@dataclass
class ComponentInfo:
    name: str
    path: str
    files: list[str] = field(default_factory=list)
    functions: int = 0
    classes: int = 0


@dataclass
class ArchitectureSnapshot:
    components: list[ComponentInfo]
    external_dependencies: list[str]
    total_files: int
    total_functions: int
    total_classes: int
    import_graph: dict[str, list[str]]  # module -> [modules it imports from this repo]


def analyze(repo_root: Path) -> ArchitectureSnapshot:
    src_root = repo_root / "src" if (repo_root / "src").is_dir() else repo_root
    components: list[ComponentInfo] = []
    total_functions = 0
    total_classes = 0
    total_files = 0
    all_source = ""
    import_graph: dict[str, list[str]] = {}

    if src_root.is_dir():
        for child in sorted(src_root.iterdir()):
            if not child.is_dir() or child.name.startswith("__"):
                continue
            py_files = sorted(p for p in child.rglob("*.py") if "__pycache__" not in p.parts)
            if not py_files:
                continue
            comp = ComponentInfo(name=child.name, path=str(child.relative_to(repo_root)))
            for f in py_files:
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                all_source += text
                total_files += 1
                comp.files.append(str(f.relative_to(repo_root)))
                funcs = len(re.findall(r"^\s*def ", text, re.M))
                classes = len(re.findall(r"^\s*class ", text, re.M))
                comp.functions += funcs
                comp.classes += classes
                total_functions += funcs
                total_classes += classes
                imports = re.findall(r"from src\.(\w+)", text)
                if imports:
                    import_graph.setdefault(str(f.relative_to(repo_root)), []).extend(
                        sorted({f"src/{m}" for m in imports})
                    )
            components.append(comp)

    external = [name for name, pattern in EXTERNAL_DEPENDENCY_SIGNALS.items() if re.search(pattern, all_source, re.I)]

    return ArchitectureSnapshot(
        components=components,
        external_dependencies=external,
        total_files=total_files,
        total_functions=total_functions,
        total_classes=total_classes,
        import_graph=import_graph,
    )


def dependents_of(snapshot: ArchitectureSnapshot, changed_files: list[str]) -> list[str]:
    """Reverse-lookup: which files import one of `changed_files`'s modules."""
    changed_modules = {Path(f).parent.as_posix() for f in changed_files}
    dependents: set[str] = set()
    for file, imports in snapshot.import_graph.items():
        if file in changed_files:
            continue
        if any(m in imports for m in changed_modules):
            dependents.add(file)
    return sorted(dependents)
