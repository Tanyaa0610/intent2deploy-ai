"""Built-in add-ons: real, tested upgrades applied to code that is already on
staging, without an AI model (mock mode).

Each add-on recognises the projects it can upgrade by fingerprints in their
files (the projects Intent2Deploy generates), reports whether it is already
applied, and produces the new contents of the files it changes plus its own
tests. A revision that uses add-ons goes through the normal plan -> approval
-> changes -> validation -> PR-into-staging flow.
"""
from __future__ import annotations

from app.services.addons.catalog import ADDONS, AddOn, apply_all, matching, read_files, statuses

__all__ = ["ADDONS", "AddOn", "apply_all", "matching", "read_files", "statuses"]
