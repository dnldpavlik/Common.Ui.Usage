"""Command-line interface and orchestration."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

from common_ui_usage.behaviors import build_behavior_index, load_behaviors
from common_ui_usage.config import (
    load_config,
    parse_definitions_config,
    parse_release_info,
    parse_repo_configs,
)
from common_ui_usage.formatting import format_report
from common_ui_usage.models import BehaviorDefinition, CompiledPattern, ReleaseInfo, RepoConfig
from common_ui_usage.patterns import build_patterns
from common_ui_usage.reports import build_scan_report, write_json_report, write_report
from common_ui_usage.scanner import scan_directory


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


def process_repo(
    repo: RepoConfig,
    patterns: list[CompiledPattern],
    release: ReleaseInfo | None,
    date_str: str,
    output_dir: Path,
    log: logging.Logger,
    behavior_index: dict[str, BehaviorDefinition] | None = None,
) -> None:
    """Scan a single repository and write both text and JSON reports."""
    log.info("Scanning: %s", repo.source_path)
    results = scan_directory(repo.source_path, patterns)

    report = format_report(results, repo.replace_path)
    txt_path = output_dir / f"{repo.report_name}-{date_str}.txt"
    write_report(report, txt_path)
    log.info("Report written: %s", txt_path)

    scan_report = build_scan_report(
        repo=repo,
        scan_date=date_str,
        release=release,
        results=results,
        behavior_index=behavior_index,
    )
    json_path = output_dir / f"{repo.report_name}-{date_str}.json"
    write_json_report(scan_report, json_path)
    log.info("JSON report written: %s", json_path)


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
    date_str = date.today().strftime("%m-%d-%Y")

    definitions_path, definitions_glob = parse_definitions_config(config)
    behavior_index: dict[str, BehaviorDefinition] | None = None
    if definitions_path is not None:
        resolved_path = args.config.parent / definitions_path
        behaviors = load_behaviors(resolved_path, definitions_glob)
        log.info("Loaded %d behavior definition(s) from %s", len(behaviors), resolved_path)
        behavior_index = build_behavior_index(behaviors) if behaviors else None

    for repo in repos:
        if not repo.source_path.is_dir():
            log.warning("Directory not found, skipping: %s", repo.source_path)
            continue
        process_repo(
            repo, patterns, release, date_str, args.output_dir, log, behavior_index
        )

    log.info("Search completed for all applications.")
    return 0


def cli() -> None:
    """Entry point for pyproject.toml console_scripts."""
    sys.exit(main())
