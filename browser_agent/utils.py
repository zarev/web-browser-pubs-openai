"""Shared helpers for the browser agent."""

from __future__ import annotations

import re

_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9]+")


def slugify(value: str) -> str:
    """Return a filesystem-safe slug."""
    cleaned = _SLUG_PATTERN.sub("-", value).strip("-")
    return cleaned or "file"
