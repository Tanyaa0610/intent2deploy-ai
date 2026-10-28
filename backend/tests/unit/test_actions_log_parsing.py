"""Parsing GitHub Actions job logs into per-step output and test results."""
from __future__ import annotations

from app.services.github.github_ops import parse_actions_log

VERBOSE_LOG = """﻿2026-10-18T10:00:00.0000000Z ##[group]Run actions/checkout@v4
2026-10-18T10:00:00.1000000Z with:
2026-10-18T10:00:00.2000000Z ##[endgroup]
2026-10-18T10:00:01.0000000Z Syncing repository: Vanshitamehta06/demo
2026-10-18T10:00:05.0000000Z ##[group]Run ruff check .
2026-10-18T10:00:05.1000000Z ruff check .
2026-10-18T10:00:05.2000000Z shell: /usr/bin/bash -e {0}
2026-10-18T10:00:05.3000000Z ##[endgroup]
2026-10-18T10:00:06.0000000Z All checks passed!
2026-10-18T10:00:07.0000000Z ##[group]Run python -m pytest -v
2026-10-18T10:00:07.1000000Z python -m pytest -v
2026-10-18T10:00:07.2000000Z ##[endgroup]
2026-10-18T10:00:08.0000000Z \x1b[1m============================= test session starts ==============================\x1b[0m
2026-10-18T10:00:08.1000000Z tests/test_api.py::test_login_page_served PASSED                         [ 50%]
2026-10-18T10:00:08.2000000Z tests/test_users.py::test_wrong_password_rejected FAILED                  [100%]
2026-10-18T10:00:08.3000000Z ========================= 1 failed, 1 passed in 0.42s ==========================
2026-10-18T10:00:08.4000000Z ##[error]Process completed with exit code 1.
"""

QUIET_LOG = """2026-10-18T10:00:07.0000000Z ##[group]Run python -m pytest -q
2026-10-18T10:00:07.2000000Z ##[endgroup]
2026-10-18T10:00:08.0000000Z .........                                                                [100%]
2026-10-18T10:00:08.1000000Z 9 passed in 2.01s
"""


def test_sections_tests_and_summary_from_verbose_log():
    parsed = parse_actions_log(VERBOSE_LOG)
    titles = [s["title"] for s in parsed["sections"]]
    assert titles == ["Run actions/checkout@v4", "Run ruff check .", "Run python -m pytest -v"]
    lint = parsed["sections"][1]["output"]
    assert lint == ["All checks passed!"]  # command echo/env inside the group header is skipped
    assert parsed["tests"] == [
        {"name": "tests/test_api.py::test_login_page_served", "outcome": "PASSED"},
        {"name": "tests/test_users.py::test_wrong_password_rejected", "outcome": "FAILED"},
    ]
    assert parsed["test_summary"] == "1 failed, 1 passed in 0.42s"
    assert any(line.startswith("ERROR: Process completed") for line in parsed["sections"][2]["output"])
    assert not any("\x1b" in line for s in parsed["sections"] for line in s["output"])  # colours stripped


def test_quiet_pytest_log_gives_summary_without_names():
    parsed = parse_actions_log(QUIET_LOG)
    assert parsed["tests"] == []
    assert parsed["test_summary"] == "9 passed in 2.01s"
