"""Text report formatting — pure functions for converting results to text."""

from __future__ import annotations

from common_ui_usage.models import FileResult


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
