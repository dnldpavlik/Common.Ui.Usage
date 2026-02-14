"""Common.Ui.Usage - Scan HTML files for shared UI component usage patterns."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
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
class RepoConfig:
    """Configuration for a single repository to scan."""

    source_path: Path
    replace_path: str
    report_name: str


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


def parse_repo_configs(raw_repos: list[dict[str, str]]) -> list[RepoConfig]:
    """Parse raw repo dicts into validated RepoConfig objects."""
    return [
        RepoConfig(
            source_path=Path(r["source_path"]),
            replace_path=r["replace_path"],
            report_name=r["report_name"],
        )
        for r in raw_repos
    ]


def write_report(content: str, output_path: Path) -> None:
    """Write report content to file, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)


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
    today = date.today()

    for repo in repos:
        if not repo.source_path.is_dir():
            log.warning("Directory not found, skipping: %s", repo.source_path)
            continue

        log.info("Scanning: %s", repo.source_path)
        results = scan_directory(repo.source_path, patterns)

        report = format_report(results, repo.replace_path)
        output_path = args.output_dir / f"{repo.report_name}-{today.strftime('%m-%d-%Y')}.txt"
        write_report(report, output_path)
        log.info("Report written: %s", output_path)

    log.info("Search completed for all applications.")
    return 0


def cli() -> None:
    """Entry point for pyproject.toml console_scripts."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
