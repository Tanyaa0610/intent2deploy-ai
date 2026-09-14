"""Unified diff generation and application.

Applying is done by parsing standard unified-diff hunks
(`@@ -l,s +l,s @@`) and replaying them against the original content in
memory, rather than shelling out to `patch`/`git apply` — this keeps
patch application inside the Python process (no extra allowlisted
executable needed) and gives precise error messages when a model-produced
hunk does not cleanly apply.
"""
from __future__ import annotations

import difflib
import re


class PatchApplyError(Exception):
    pass


def make_unified_diff(file_path: str, old_content: str, new_content: str) -> str:
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="\n",
    )
    return "".join(diff)


def make_new_file_diff(file_path: str, content: str) -> str:
    new_lines = content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        [], new_lines, fromfile="/dev/null", tofile=f"b/{file_path}", lineterm="\n"
    )
    return "".join(diff)


def make_delete_file_diff(file_path: str, content: str) -> str:
    old_lines = content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, [], fromfile=f"a/{file_path}", tofile="/dev/null", lineterm="\n"
    )
    return "".join(diff)


def count_patch_lines(patch: str) -> int:
    return sum(
        1
        for line in patch.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply_patch(old_content: str, patch: str) -> str:
    """Apply a unified diff (as produced by `make_unified_diff`) to
    `old_content` and return the resulting content.

    Handles the pure-addition case (`/dev/null` source, i.e. new file)
    by returning the added lines directly.
    """
    lines = patch.splitlines()
    if not lines:
        return old_content

    if any(line.startswith("--- /dev/null") for line in lines):
        # New file: every hunk is pure additions.
        added = [line[1:] for line in lines if line.startswith("+") and not line.startswith("+++")]
        return "\n".join(added) + ("\n" if added else "")

    src_lines = old_content.splitlines(keepends=True)
    result: list[str] = []
    src_idx = 0  # 0-based index into src_lines
    i = 0
    n = len(lines)
    hunk_found = False

    while i < n:
        m = _HUNK_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        hunk_found = True
        old_start = int(m.group(1))
        # Copy unchanged lines before this hunk.
        result.extend(src_lines[src_idx : old_start - 1])
        src_idx = old_start - 1
        i += 1
        while i < n and not lines[i].startswith("@@"):
            line = lines[i]
            if line.startswith(" "):
                result.append(src_lines[src_idx] if src_idx < len(src_lines) else line[1:] + "\n")
                src_idx += 1
            elif line.startswith("-") and not line.startswith("---"):
                src_idx += 1
            elif line.startswith("+") and not line.startswith("+++"):
                text = line[1:]
                result.append(text + "\n" if not text.endswith("\n") else text)
            i += 1
    if not hunk_found:
        raise PatchApplyError("No valid hunk headers found in patch.")

    result.extend(src_lines[src_idx:])
    joined = "".join(result)
    # Normalize: unified_diff's lineterm handling can leave content without
    # a trailing newline consistent with the original; strip a single
    # trailing extra newline if one was introduced.
    return joined
