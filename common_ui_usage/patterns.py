"""Pattern building — compiles raw pattern strings into regex patterns."""

from __future__ import annotations

import re

from common_ui_usage.models import CompiledPattern

NEGATIVE_LOOKAHEAD = r"(?![!?-])"


def build_pattern(raw: str) -> CompiledPattern:
    """Build a CompiledPattern from a raw pattern string."""
    regex = re.escape(raw) + NEGATIVE_LOOKAHEAD if raw.startswith("<") else re.escape(raw)
    return CompiledPattern(original=raw, regex=re.compile(regex))


def build_patterns(raw_patterns: list[str]) -> list[CompiledPattern]:
    """Build compiled regex patterns from raw pattern strings."""
    return [build_pattern(p) for p in raw_patterns]
