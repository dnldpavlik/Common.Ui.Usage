"""Configuration validation, parsing, and loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common_ui_usage.models import ReleaseInfo, RepoConfig, RouteMapping


def _validate_route_map(route_map: Any, repo_index: int) -> None:
    """Validate a single repo's route_map structure."""
    if not isinstance(route_map, list):
        raise ValueError(f"application_repo[{repo_index}] 'route_map' must be a list")
    for j, route in enumerate(route_map):
        for key in ("path_pattern", "route", "name"):
            if key not in route:
                raise ValueError(
                    f"application_repo[{repo_index}].route_map[{j}] missing required key: '{key}'"
                )


def _validate_repo(repo: dict[str, Any], index: int) -> None:
    """Validate a single application_repo entry."""
    for key in ("source_path", "replace_path", "report_name"):
        if key not in repo:
            raise ValueError(f"application_repo[{index}] missing required key: '{key}'")
    if "route_map" in repo:
        _validate_route_map(repo["route_map"], index)
    if "base_url" in repo and not isinstance(repo["base_url"], str):
        raise ValueError(f"application_repo[{index}] 'base_url' must be a string")


def _validate_release(release: Any) -> None:
    """Validate the optional release config block."""
    if not isinstance(release, dict):
        raise ValueError("Config 'release' must be an object")
    for key in ("version", "affected_components", "date"):
        if key not in release:
            raise ValueError(f"Config 'release' missing required key: '{key}'")


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
        _validate_repo(repo, i)
    if "release" in config:
        _validate_release(config["release"])
    if "definitions_path" in config and not isinstance(config["definitions_path"], str):
        raise ValueError("Config 'definitions_path' must be a string")
    if "definitions_glob" in config and not isinstance(config["definitions_glob"], str):
        raise ValueError("Config 'definitions_glob' must be a string")


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


def parse_definitions_config(config: dict[str, Any]) -> tuple[Path | None, str]:
    """Parse optional definitions config. Returns (path_or_none, glob_pattern)."""
    raw_path = config.get("definitions_path")
    glob_pattern = config.get("definitions_glob", "*.behavior.json")
    if raw_path is None:
        return None, glob_pattern
    return Path(raw_path), glob_pattern


def load_config(config_path: Path) -> dict[str, Any]:
    """Load and validate configuration from JSON file."""
    with open(config_path) as f:
        config: dict[str, Any] = json.load(f)
    validate_config(config)
    return config
