"""Behavior definition loading, indexing, and component match enrichment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_ui_usage.models import BehaviorDefinition, BreakingChange, ComponentMatch


def extract_component_name(tag: str) -> str:
    """Strip leading '<' from a scanner pattern to get the component name.

    Non-tag patterns (without leading '<') are returned unchanged.
    """
    if tag.startswith("<"):
        return tag[1:]
    return tag


def _parse_breaking_changes(raw: list[dict[str, Any]]) -> tuple[BreakingChange, ...]:
    """Parse raw breaking change dicts into BreakingChange tuples."""
    return tuple(
        BreakingChange(version=bc["version"], description=bc["description"]) for bc in raw
    )


def load_behavior_file(file_path: Path) -> BehaviorDefinition:
    """Load a single behavior definition from a JSON file."""
    with open(file_path) as f:
        data: dict[str, Any] = json.load(f)
    return BehaviorDefinition(
        component=data["component"],
        version=data["version"],
        tag=data["tag"],
        filename=file_path.name,
        breaking_changes=_parse_breaking_changes(data.get("breaking_changes", [])),
    )


def load_behaviors(
    definitions_path: Path,
    definitions_glob: str,
) -> tuple[BehaviorDefinition, ...]:
    """Load all behavior definitions matching the glob pattern.

    Returns an empty tuple if the directory does not exist.
    """
    if not definitions_path.is_dir():
        return ()
    files = sorted(definitions_path.glob(definitions_glob))
    return tuple(load_behavior_file(f) for f in files)


def build_behavior_index(
    behaviors: tuple[BehaviorDefinition, ...],
) -> dict[str, BehaviorDefinition]:
    """Build a lookup index keyed by component name. Pure function."""
    return {b.component: b for b in behaviors}


def find_behavior_for_tag(
    tag: str,
    index: dict[str, BehaviorDefinition],
) -> BehaviorDefinition | None:
    """Find a behavior definition matching a scanner tag. Pure function."""
    name = extract_component_name(tag)
    return index.get(name)


def check_breaking_changes(
    behavior: BehaviorDefinition,
    release_version: str | None,
) -> tuple[bool, str | None]:
    """Check if a behavior has breaking changes for a given release version.

    Returns (has_breaking, description_or_none). Pure function.
    """
    if release_version is None or not behavior.breaking_changes:
        return False, None
    matching = [
        bc.description for bc in behavior.breaking_changes if bc.version == release_version
    ]
    if not matching:
        return False, None
    return True, "; ".join(matching)


def enrich_component_match(
    component: ComponentMatch,
    index: dict[str, BehaviorDefinition],
    release_version: str | None,
) -> ComponentMatch:
    """Enrich a ComponentMatch with behavior definition data. Pure function.

    Returns a new frozen instance with behavior fields populated.
    """
    behavior = find_behavior_for_tag(component.tag, index)
    if behavior is None:
        return component
    has_breaking, breaking_desc = check_breaking_changes(behavior, release_version)
    return ComponentMatch(
        tag=component.tag,
        lines=component.lines,
        behavior_definition=behavior.filename,
        has_breaking_changes=has_breaking,
        breaking_change=breaking_desc,
    )
