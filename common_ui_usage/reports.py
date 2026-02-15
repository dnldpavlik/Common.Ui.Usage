"""Report building and writing — structured reports and file output."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from common_ui_usage.models import FileResult, ReleaseInfo, RepoConfig, ScanReport
from common_ui_usage.routing import build_resolved_pages


def build_scan_report(
    repo: RepoConfig,
    scan_date: str,
    release: ReleaseInfo | None,
    results: list[FileResult],
) -> ScanReport:
    """Build a structured ScanReport from scan results. Pure function."""
    pages = build_resolved_pages(results, repo.replace_path, repo.route_map)
    return ScanReport(
        application=repo.report_name,
        base_url=repo.base_url,
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


def write_report(content: str, output_path: Path) -> None:
    """Write report content to file, creating parent directories as needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content)


def write_json_report(report: ScanReport, output_path: Path) -> None:
    """Write structured JSON scan report to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = scan_report_to_dict(report)
    output_path.write_text(json.dumps(data, indent=2) + "\n")
