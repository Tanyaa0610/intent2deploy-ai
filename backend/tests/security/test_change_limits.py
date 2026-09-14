"""Oversized patch / too-many-files rejection (master spec §34, §38)."""
from __future__ import annotations

import json

from app.services.codegen.codegen import ChangeGenerationLimitError, generate_changes
from app.services.providers.base import LLMProvider, LLMResponse, LLMUsage


def _fake_provider(text: str) -> LLMProvider:
    class _P(LLMProvider):
        name = "fake"

        def complete(self, prompt_name, rendered_prompt, context):
            return LLMResponse(text=text, usage=LLMUsage(), model="fake", provider=self.name, is_mock=True)

    return _P()


def test_oversized_patch_is_rejected(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_patch_lines", 5)

    target = tmp_path / "f.py"
    target.write_text("line\n" * 20)

    huge_patch = "--- a/f.py\n+++ b/f.py\n@@ -1,20 +1,20 @@\n" + "\n".join(f"+added line {i}" for i in range(50))
    payload = json.dumps(
        {"changes": [{"file": "f.py", "operation": "modify", "reason": "x", "patch": huge_patch, "confidence": 0.9, "risks": []}]}
    )
    provider = _fake_provider(payload)

    try:
        generate_changes(provider, tmp_path, ["f.py"], "intent", "summary", [])
        assert False, "expected ChangeGenerationLimitError"
    except ChangeGenerationLimitError:
        pass


def test_too_many_files_changed_is_rejected(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "max_files_changed", 2)

    changes = [
        {"file": f"f{i}.py", "operation": "modify", "reason": "x", "patch": "", "confidence": 0.9, "risks": []}
        for i in range(5)
    ]
    provider = _fake_provider(json.dumps({"changes": changes}))

    try:
        generate_changes(provider, tmp_path, [], "intent", "summary", [])
        assert False, "expected ChangeGenerationLimitError"
    except ChangeGenerationLimitError:
        pass
