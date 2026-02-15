"""Common.Ui.Usage - Scan HTML files for shared UI component usage patterns."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data structures (immutable)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

NEGATIVE_LOOKAHEAD = r"(?![!?-])"


def build_pattern(raw: str) -> tuple[str, re.Pattern[str]]:
    """Build a single (original, compiled_regex) tuple from a raw pattern string."""
    regex = re.escape(raw) + NEGATIVE_LOOKAHEAD if raw.startswith("<") else re.escape(raw)
    return (raw, re.compile(regex))


def build_patterns(raw_patterns: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    """Build compiled regex patterns from raw pattern strings."""
    return [build_pattern(p) for p in raw_patterns]


def scan_line(
    line: str,
    line_num: int,
    patterns: list[tuple[str, re.Pattern[str]]],
) -> list[MatchResult]:
    """Scan a single line against all patterns. Pure function."""
    results: list[MatchResult] = []
    for original, compiled in patterns:
        for match in compiled.finditer(line):
            start, end = match.span()
            excerpt = line[start:end].strip()
            results.append(MatchResult(line_num=line_num, excerpt=excerpt, pattern=original))
    return results


def format_file_result(result: FileResult, replace_path: str) -> str:
    """Format a single file's results as a report section. Pure function."""
    display_path = result.file_path.replace(replace_path, "")
    lines = [f"\n** {display_path} **"]
    for m in result.matches:
        lines.append(f"Line {m.line_num}: {m.excerpt} (Pattern: {m.pattern})")
    return "\n".join(lines)


def format_report(results: list[FileResult], replace_path: str) -> str:
    """Format all results into a complete report string. Pure function."""
    sections = [format_file_result(r, replace_path) for r in results]
    return "\n".join(sections) + "\n" if sections else ""


def resolve_route(
    file_path: str,
    replace_path: str,
    route_map: tuple[RouteMapping, ...],
) -> tuple[str | None, str | None]:
    """Resolve a file path to an application route and page name.

    Returns (route, page_name) or (None, None) if no route matches.
    """
    cleaned = file_path.replace(replace_path, "")
    for mapping in route_map:
        if fnmatch(cleaned, mapping.path_pattern):
            return mapping.route, mapping.name
    return None, None


def build_resolved_pages(
    results: list[FileResult],
    replace_path: str,
    route_map: tuple[RouteMapping, ...],
) -> tuple[ResolvedPage, ...]:
    """Convert FileResults into ResolvedPages with route info and grouped components."""
    pages: list[ResolvedPage] = []
    for file_result in results:
        route, page_name = resolve_route(file_result.file_path, replace_path, route_map)
        # Group matches by tag
        tag_lines: dict[str, list[int]] = {}
        for m in file_result.matches:
            tag_lines.setdefault(m.pattern, []).append(m.line_num)
        components = tuple(
            ComponentMatch(tag=tag, lines=tuple(lines)) for tag, lines in tag_lines.items()
        )
        pages.append(
            ResolvedPage(
                file_path=file_result.file_path.replace(replace_path, ""),
                route=route,
                page_name=page_name,
                components=components,
            )
        )
    return tuple(pages)


def build_scan_report(
    application: str,
    base_url: str | None,
    scan_date: str,
    release: ReleaseInfo | None,
    results: list[FileResult],
    replace_path: str,
    route_map: tuple[RouteMapping, ...],
) -> ScanReport:
    """Build a structured ScanReport from scan results. Pure function."""
    pages = build_resolved_pages(results, replace_path, route_map)
    return ScanReport(
        application=application,
        base_url=base_url,
        scan_date=scan_date,
        release=release,
        pages=pages,
    )


def _tuples_to_lists(obj: Any) -> Any:
    """Recursively convert tuples to lists for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _tuples_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_tuples_to_lists(item) for item in obj]
    return obj


def scan_report_to_dict(report: ScanReport) -> dict[str, Any]:
    """Convert a ScanReport to a JSON-serializable dict."""
    raw: dict[str, Any] = asdict(report)
    result: dict[str, Any] = _tuples_to_lists(raw)
    return result


# ---------------------------------------------------------------------------
# I/O functions
# ---------------------------------------------------------------------------


def find_html_files(directory: Path) -> Iterator[Path]:
    """Yield all .html files under directory, recursively."""
    for root, _, files in os.walk(directory):
        for filename in sorted(files):
            if filename.endswith(".html"):
                yield Path(root) / filename


def scan_file(
    file_path: Path,
    patterns: list[tuple[str, re.Pattern[str]]],
) -> FileResult:
    """Scan a single HTML file for pattern matches."""
    matches: list[MatchResult] = []
    with open(file_path) as f:
        for line_num, line in enumerate(f, start=1):
            matches.extend(scan_line(line, line_num, patterns))
    return FileResult(file_path=str(file_path), matches=tuple(matches))


def scan_directory(
    directory: Path,
    patterns: list[tuple[str, re.Pattern[str]]],
) -> list[FileResult]:
    """Scan all HTML files in directory tree. Returns only files with matches."""
    results: list[FileResult] = []
    for html_file in find_html_files(directory):
        result = scan_file(html_file, patterns)
        if result.matches:
            results.append(result)
    return results


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and validate configuration from JSON file."""
    with open(config_path) as f:
        config: dict[str, Any] = json.load(f)
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    """Validate config structure. Raises ValueError on invalid config."""
    if "patterns" not in config:
        raise ValueError("Config missing required key: 'patterns'")
    if "application_repo" not in config:
        raise ValueError("Config missing required key: 'application_repo'")
    if not isinstance(config["patterns"], list) or not config["patterns"]:
        raise ValueError("Config 'patterns' must be a non-empty list")
    if not isinstance(config["application_repo"], list):
        raise ValueError("Config 'application_repo' must be a list")
    for i, repo in enumerate(config["application_repo"]):
        for key in ("source_path", "replace_path", "report_name"):
            if key not in repo:
                raise ValueError(f"application_repo[{i}] missing required key: '{key}'")
        if "route_map" in repo:
            if not isinstance(repo["route_map"], list):
                raise ValueError(f"application_repo[{i}] 'route_map' must be a list")
            for j, route in enumerate(repo["route_map"]):
                for key in ("path_pattern", "route", "name"):
                    if key not in route:
                        raise ValueError(
                            f"application_repo[{i}].route_map[{j}] missing required key: '{key}'"
                        )
        if "base_url" in repo and not isinstance(repo["base_url"], str):
            raise ValueError(f"application_repo[{i}] 'base_url' must be a string")
    if "release" in config:
        release = config["release"]
        if not isinstance(release, dict):
            raise ValueError("Config 'release' must be an object")
        for key in ("version", "affected_components", "date"):
            if key not in release:
                raise ValueError(f"Config 'release' missing required key: '{key}'")


def parse_repo_configs(raw_repos: list[dict[str, Any]]) -> list[RepoConfig]:
    """Parse raw repo dicts into validated RepoConfig objects."""
    configs: list[RepoConfig] = []
    for r in raw_repos:
        route_map = tuple(
            RouteMapping(
                path_pattern=rm["path_pattern"],
                route=rm["route"],
                name=rm["name"],
            )
            for rm in r.get("route_map", [])
        )
        configs.append(
            RepoConfig(
                source_path=Path(r["source_path"]),
                replace_path=r["replace_path"],
                report_name=r["report_name"],
                base_url=r.get("base_url"),
                route_map=route_map,
            )
        )
    return configs


def parse_release_info(config: dict[str, Any]) -> ReleaseInfo | None:
    """Parse optional release info from config. Returns None if not present."""
    raw = config.get("release")
    if raw is None:
        return None
    return ReleaseInfo(
        version=raw["version"],
        affected_components=tuple(raw["affected_components"]),
        release_date=raw["date"],
    )


def write_report(content: str, output_path: Path) -> None:
    """Write report content to file, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)


def write_json_report(report: ScanReport, output_path: Path) -> None:
    """Write structured JSON scan report to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = scan_report_to_dict(report)
    output_path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="common-ui-usage",
        description="Scan HTML files for shared UI component usage patterns.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to configuration file (default: config.json)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("Reports"),
        help="Directory for output reports (default: Reports/)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns exit code."""
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )
    log = logging.getLogger(__name__)

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        log.error("Config file not found: %s", args.config)
        return 1
    except (json.JSONDecodeError, ValueError) as e:
        log.error("Invalid config: %s", e)
        return 1

    patterns = build_patterns(config["patterns"])
    repos = parse_repo_configs(config["application_repo"])
    release = parse_release_info(config)
    today = date.today()
    date_str = today.strftime("%m-%d-%Y")

    for repo in repos:
        if not repo.source_path.is_dir():
            log.warning("Directory not found, skipping: %s", repo.source_path)
            continue

        log.info("Scanning: %s", repo.source_path)
        results = scan_directory(repo.source_path, patterns)

        report = format_report(results, repo.replace_path)
        txt_path = args.output_dir / f"{repo.report_name}-{date_str}.txt"
        write_report(report, txt_path)
        log.info("Report written: %s", txt_path)

        scan_report = build_scan_report(
            application=repo.report_name,
            base_url=repo.base_url,
            scan_date=date_str,
            release=release,
            results=results,
            replace_path=repo.replace_path,
            route_map=repo.route_map,
        )
        json_path = args.output_dir / f"{repo.report_name}-{date_str}.json"
        write_json_report(scan_report, json_path)
        log.info("JSON report written: %s", json_path)

    log.info("Search completed for all applications.")
    return 0


def cli() -> None:
    """Entry point for pyproject.toml console_scripts."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
