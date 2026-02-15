"""Immutable data structures for the scanning pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CompiledPattern:
    """A search pattern with its original string and compiled regex."""

    original: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class MatchResult:
    """A single pattern match within a file."""

    line_num: int
    excerpt: str
    pattern: str


@dataclass(frozen=True)
class FileResult:
    """All matches found in a single file."""

    file_path: str
    matches: tuple[MatchResult, ...]


@dataclass(frozen=True)
class RouteMapping:
    """Maps a file path glob to an application route."""

    path_pattern: str
    route: str
    name: str


@dataclass(frozen=True)
class RepoConfig:
    """Configuration for a single repository to scan."""

    source_path: Path
    replace_path: str
    report_name: str
    base_url: str | None = None
    route_map: tuple[RouteMapping, ...] = ()


@dataclass(frozen=True)
class ComponentMatch:
    """A component found on a page with all its match locations."""

    tag: str
    lines: tuple[int, ...]


@dataclass(frozen=True)
class ResolvedPage:
    """A scanned file with its route resolved."""

    file_path: str
    route: str | None
    page_name: str | None
    components: tuple[ComponentMatch, ...]


@dataclass(frozen=True)
class ReleaseInfo:
    """Metadata about the library release being scanned for."""

    version: str
    affected_components: tuple[str, ...]
    release_date: str


@dataclass(frozen=True)
class ScanReport:
    """Complete structured scan output for one application."""

    application: str
    base_url: str | None
    scan_date: str
    release: ReleaseInfo | None
    pages: tuple[ResolvedPage, ...]
