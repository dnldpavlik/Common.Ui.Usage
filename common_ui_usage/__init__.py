"""Common.Ui.Usage - Scan HTML files for shared UI component usage patterns."""

from common_ui_usage.behaviors import (
    build_behavior_index,
    check_breaking_changes,
    enrich_component_match,
    extract_component_name,
    find_behavior_for_tag,
    load_behavior_file,
    load_behaviors,
)
from common_ui_usage.cli import cli, main, parse_args, process_repo
from common_ui_usage.config import (
    load_config,
    parse_definitions_config,
    parse_release_info,
    parse_repo_configs,
    validate_config,
)
from common_ui_usage.formatting import format_file_result, format_report
from common_ui_usage.models import (
    BehaviorDefinition,
    BreakingChange,
    CompiledPattern,
    ComponentMatch,
    FileResult,
    MatchResult,
    ReleaseInfo,
    RepoConfig,
    ResolvedPage,
    RouteMapping,
    ScanReport,
)
from common_ui_usage.patterns import NEGATIVE_LOOKAHEAD, build_pattern, build_patterns
from common_ui_usage.reports import (
    build_scan_report,
    scan_report_to_dict,
    write_json_report,
    write_report,
)
from common_ui_usage.routing import (
    build_resolved_page,
    build_resolved_pages,
    group_matches_by_tag,
    resolve_route,
)
from common_ui_usage.scanner import find_html_files, scan_directory, scan_file, scan_line

__all__ = [
    "BehaviorDefinition",
    "BreakingChange",
    "NEGATIVE_LOOKAHEAD",
    "CompiledPattern",
    "ComponentMatch",
    "FileResult",
    "MatchResult",
    "ReleaseInfo",
    "RepoConfig",
    "ResolvedPage",
    "RouteMapping",
    "ScanReport",
    "build_behavior_index",
    "build_pattern",
    "build_patterns",
    "build_resolved_page",
    "build_resolved_pages",
    "build_scan_report",
    "check_breaking_changes",
    "cli",
    "enrich_component_match",
    "extract_component_name",
    "find_behavior_for_tag",
    "find_html_files",
    "format_file_result",
    "format_report",
    "group_matches_by_tag",
    "load_behavior_file",
    "load_behaviors",
    "load_config",
    "main",
    "parse_args",
    "parse_definitions_config",
    "parse_release_info",
    "parse_repo_configs",
    "process_repo",
    "resolve_route",
    "scan_directory",
    "scan_file",
    "scan_line",
    "scan_report_to_dict",
    "validate_config",
    "write_json_report",
    "write_report",
]
