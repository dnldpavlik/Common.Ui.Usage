"""Route resolution — maps file paths to application routes."""

from __future__ import annotations

from fnmatch import fnmatch

from common_ui_usage.models import (
    ComponentMatch,
    FileResult,
    MatchResult,
    ResolvedPage,
    RouteMapping,
)


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


def group_matches_by_tag(matches: tuple[MatchResult, ...]) -> tuple[ComponentMatch, ...]:
    """Group flat match results into ComponentMatches keyed by tag. Pure function."""
    tag_lines: dict[str, list[int]] = {}
    for m in matches:
        tag_lines.setdefault(m.pattern, []).append(m.line_num)
    return tuple(ComponentMatch(tag=tag, lines=tuple(lines)) for tag, lines in tag_lines.items())


def build_resolved_page(
    file_result: FileResult,
    replace_path: str,
    route_map: tuple[RouteMapping, ...],
) -> ResolvedPage:
    """Convert a single FileResult into a ResolvedPage. Pure function."""
    route, page_name = resolve_route(file_result.file_path, replace_path, route_map)
    return ResolvedPage(
        file_path=file_result.file_path.replace(replace_path, ""),
        route=route,
        page_name=page_name,
        components=group_matches_by_tag(file_result.matches),
    )


def build_resolved_pages(
    results: list[FileResult],
    replace_path: str,
    route_map: tuple[RouteMapping, ...],
) -> tuple[ResolvedPage, ...]:
    """Convert FileResults into ResolvedPages with route info and grouped components."""
    return tuple(build_resolved_page(fr, replace_path, route_map) for fr in results)
