"""Pipeline Router - Central routing and repository for pipeline configurations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, Field

# =============================================================================
# Configuration Models
# =============================================================================


class RepositoryConfig(BaseModel):
    """Repository configuration with type and type-specific settings."""

    type: str
    config: dict[str, Any] = Field(default_factory=dict)

    def to_kwargs(self) -> dict[str, Any]:
        return dict(self.config)


class DestinationConfig(BaseModel):
    """Destination configuration specifying repository and output path."""

    repository: str
    path: str = Field(default="")


class PipelineRef(BaseModel):
    """Pipeline reference with optional runtime config."""

    name: str
    config: dict[str, Any] = Field(default_factory=dict)


class RouteConfig(BaseModel):
    """Route configuration with match criteria, pipeline, and destinations."""

    match: dict[str, Any] = Field(default_factory=dict)
    pipeline: PipelineRef
    destinations: dict[str, DestinationConfig] = Field(default_factory=dict)


class PipelineConfig(BaseModel):
    """Pipeline configuration with list of transforms to apply."""

    transforms: list[str] = Field(default_factory=list)


@dataclass
class MatchResult:
    """Result of a successful route match."""

    route_name: str
    route_config: RouteConfig
    pipeline_name: str
    pipeline_config: PipelineConfig
    pipeline_config_override: dict[str, Any] = field(default_factory=dict)
    destinations: dict[str, DestinationConfig] = field(default_factory=dict)


_REGEX_METACHARACTERS = re.compile(r"[\^$.*+?{}()|[\]\\]")


def _is_regex(value: str) -> bool:
    return bool(_REGEX_METACHARACTERS.search(value))


def _match_value(pattern: Any, value: Any) -> bool:
    """Match a pattern against a value with regex and list support."""
    if pattern is None:
        return True
    if value is None:
        return False

    if isinstance(pattern, list):
        return any(_match_value(p, value) for p in pattern)

    if isinstance(pattern, str):
        value_str = str(value)
        if _is_regex(pattern):
            try:
                return bool(re.search(pattern, value_str))
            except re.error:
                return pattern == value_str
        return pattern == value_str

    return pattern == value


def _match_all_criteria(criteria: dict[str, Any], values: dict[str, Any]) -> bool:
    return all(_match_value(criteria[key], values.get(key)) for key in criteria)


class Router:
    """Singleton router for pipeline configuration management."""

    _instance: ClassVar[Router | None] = None
    _initialized: ClassVar[bool] = False

    def __init__(
        self,
        repositories: dict[str, RepositoryConfig],
        routes: dict[str, RouteConfig],
        pipelines: dict[str, PipelineConfig],
    ) -> None:
        self._repositories = repositories
        self._routes = routes
        self._pipelines = pipelines

    @classmethod
    def initialize(cls, config: Any | None = None) -> Router:
        """Initialize router from config. Loads from settings if config is None."""
        if config is None:
            from etl.config.settings import get_settings

            config = get_settings().pipeline_configuration

        cls._instance = cls(
            repositories=cls._parse_repositories(config.repositories),
            routes=cls._parse_routes(config.routes),
            pipelines=cls._parse_pipelines(config.pipelines),
        )
        cls._initialized = True
        return cls._instance

    @classmethod
    def get_instance(cls) -> Router:
        """Get the singleton instance. Raises RuntimeError if not initialized."""
        if not cls._initialized or cls._instance is None:
            raise RuntimeError("Router not initialized. Call Router.initialize() first.")
        return cls._instance

    @classmethod
    def is_initialized(cls) -> bool:
        return cls._initialized and cls._instance is not None

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (useful for testing)."""
        cls._instance = None
        cls._initialized = False

    @classmethod
    def _parse_repositories(cls, raw: dict[str, dict]) -> dict[str, RepositoryConfig]:
        return {
            name: RepositoryConfig(
                type=data.get("type", ""),
                config={k: v for k, v in data.items() if k != "type"},
            )
            for name, data in raw.items()
        }

    @classmethod
    def _parse_pipelines(cls, raw: dict[str, dict]) -> dict[str, PipelineConfig]:
        return {name: PipelineConfig(**data) for name, data in raw.items()}

    @classmethod
    def _parse_routes(cls, raw: dict[str, dict]) -> dict[str, RouteConfig]:
        result = {}
        for name, data in raw.items():
            pipeline_raw = data["pipeline"]
            if isinstance(pipeline_raw, str):
                pipeline_ref = PipelineRef(name=pipeline_raw)
            else:
                pipeline_ref = PipelineRef(
                    name=pipeline_raw["name"],
                    config=pipeline_raw.get("config", {}),
                )
            result[name] = RouteConfig(
                match=data.get("match", {}),
                pipeline=pipeline_ref,
                destinations={
                    dest_name: DestinationConfig(**dest_data)
                    for dest_name, dest_data in data.get("destinations", {}).items()
                },
            )
        return result

    def get_repository(self, name: str) -> RepositoryConfig | None:
        return self._repositories.get(name)

    def list_repositories(self) -> dict[str, RepositoryConfig]:
        return dict(self._repositories)

    def find_repositories(self, **criteria: Any) -> dict[str, RepositoryConfig]:
        """Find repositories matching criteria (searches type and config fields)."""
        return {
            name: repo
            for name, repo in self._repositories.items()
            if _match_all_criteria(criteria, {"type": repo.type, **repo.config})
        }

    def get_route(self, name: str) -> RouteConfig | None:
        return self._routes.get(name)

    def list_routes(self) -> dict[str, RouteConfig]:
        return dict(self._routes)

    def get_routes_by_criteria(self, **criteria: Any) -> dict[str, RouteConfig]:
        """Find routes whose match config contains the given criteria values."""
        return {
            name: route for name, route in self._routes.items() if self._route_has_matching_criteria(route, criteria)
        }

    def _route_has_matching_criteria(self, route: RouteConfig, criteria: dict[str, Any]) -> bool:
        for key, value in criteria.items():
            route_pattern = route.match.get(key)
            if route_pattern is None or not _match_value(route_pattern, value):
                return False
        return True

    def get_pipeline(self, name: str) -> PipelineConfig | None:
        return self._pipelines.get(name)

    def list_pipelines(self) -> dict[str, PipelineConfig]:
        return dict(self._pipelines)

    def match_route(self, **values: Any) -> MatchResult | None:
        """Find first matching route for given values. Returns None if no match."""
        for route_name, route in self._routes.items():
            if result := self._try_match_route(route_name, route, values):
                return result
        return None

    def match_all_routes(self, **values: Any) -> list[MatchResult]:
        """Find all matching routes for given values."""
        return [
            result
            for route_name, route in self._routes.items()
            if (result := self._try_match_route(route_name, route, values))
        ]

    def _try_match_route(self, route_name: str, route: RouteConfig, values: dict[str, Any]) -> MatchResult | None:
        if not _match_all_criteria(route.match, values):
            return None

        pipeline_config = self._pipelines.get(route.pipeline.name)
        if not pipeline_config:
            return None

        return MatchResult(
            route_name=route_name,
            route_config=route,
            pipeline_name=route.pipeline.name,
            pipeline_config=pipeline_config,
            pipeline_config_override=route.pipeline.config,
            destinations=route.destinations,
        )

    def batch_match(self, items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group items by their matching route name."""
        route_to_items: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if match := self.match_route(**item):
                route_to_items.setdefault(match.route_name, []).append(item)
        return route_to_items

    def build_pipeline_config(
        self,
        match_result: MatchResult,
        source_objects: list[str],
        source_repository: str,
    ) -> dict[str, Any]:
        """Build pipeline config dict for Pipeline.create()."""
        return {
            "transforms": match_result.pipeline_config.transforms,
            "sources": {
                "primary": {
                    "repository": source_repository,
                    "objects": source_objects,
                    "path": ".",
                }
            },
            "destinations": {
                name: {"repository": dest.repository, "path": dest.path}
                for name, dest in match_result.destinations.items()
            },
        }


def get_router() -> Router:
    return Router.get_instance()


def initialize_router(config: Any | None = None) -> Router:
    """Initialize the Router singleton. Loads from settings if config is None."""
    return Router.initialize(config)
