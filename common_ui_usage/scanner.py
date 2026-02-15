"""File discovery and scanning — finds HTML files and scans them for patterns."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from common_ui_usage.models import CompiledPattern, FileResult, MatchResult


def scan_line(
    line: str,
    line_num: int,
    patterns: list[CompiledPattern],
) -> list[MatchResult]:
    """Scan a single line against all patterns. Pure function."""
    results: list[MatchResult] = []
    for cp in patterns:
        for match in cp.regex.finditer(line):
            start, end = match.span()
            excerpt = line[start:end].strip()
            results.append(MatchResult(line_num=line_num, excerpt=excerpt, pattern=cp.original))
    return results


def find_html_files(directory: Path) -> Iterator[Path]:
    """Yield all .html files under directory, recursively."""
    for root, _, files in os.walk(directory):
        for filename in sorted(files):
            if filename.endswith(".html"):
                yield Path(root) / filename


def scan_file(
    file_path: Path,
    patterns: list[CompiledPattern],
) -> FileResult:
    """Scan a single HTML file for pattern matches."""
    matches: list[MatchResult] = []
    with open(file_path) as f:
        for line_num, line in enumerate(f, start=1):
            matches.extend(scan_line(line, line_num, patterns))
    return FileResult(file_path=str(file_path), matches=tuple(matches))


def scan_directory(
    directory: Path,
    patterns: list[CompiledPattern],
) -> list[FileResult]:
    """Scan all HTML files in directory tree. Returns only files with matches."""
    results: list[FileResult] = []
    for html_file in find_html_files(directory):
        result = scan_file(html_file, patterns)
        if result.matches:
            results.append(result)
    return results
