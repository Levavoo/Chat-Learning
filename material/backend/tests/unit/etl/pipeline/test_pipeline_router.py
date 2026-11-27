from unittest.mock import MagicMock, patch

import pytest

from etl.pipeline.router import (
    DestinationConfig,
    MatchResult,
    PipelineConfig,
    PipelineRef,
    RepositoryConfig,
    RouteConfig,
    Router,
    _is_regex,
    _match_all_criteria,
    _match_value,
    get_router,
    initialize_router,
)


class TestRepositoryConfig:
    def test_to_kwargs_returns_config_dict(self):
        config = RepositoryConfig(type="s3", config={"bucket": "test", "region": "eu-central-1"})

        result = config.to_kwargs()

        assert result == {"bucket": "test", "region": "eu-central-1"}

    def test_to_kwargs_returns_empty_dict_when_no_config(self):
        config = RepositoryConfig(type="local")

        result = config.to_kwargs()

        assert result == {}


class TestIsRegex:
    def test_is_regex_returns_true_for_dot_star(self):
        assert _is_regex(".*") is True

    def test_is_regex_returns_true_for_caret(self):
        assert _is_regex("^start") is True

    def test_is_regex_returns_true_for_dollar(self):
        assert _is_regex("end$") is True

    def test_is_regex_returns_true_for_brackets(self):
        assert _is_regex("[a-z]") is True

    def test_is_regex_returns_true_for_question_mark(self):
        assert _is_regex("ab?c") is True

    def test_is_regex_returns_true_for_plus(self):
        assert _is_regex("a+") is True

    def test_is_regex_returns_true_for_pipe(self):
        assert _is_regex("a|b") is True

    def test_is_regex_returns_true_for_parentheses(self):
        assert _is_regex("(abc)") is True

    def test_is_regex_returns_true_for_curly_braces(self):
        assert _is_regex("a{2,3}") is True

    def test_is_regex_returns_false_for_plain_string(self):
        assert _is_regex("simple_text") is False

    def test_is_regex_returns_false_for_hyphen_underscore(self):
        assert _is_regex("my-file_name") is False


class TestMatchValue:
    def test_match_value_none_pattern_matches_anything(self):
        assert _match_value(None, "anything") is True
        assert _match_value(None, 123) is True

    def test_match_value_none_value_returns_false(self):
        assert _match_value("pattern", None) is False

    def test_match_value_exact_string_match(self):
        assert _match_value("exact", "exact") is True
        assert _match_value("exact", "different") is False

    def test_match_value_regex_pattern_matches(self):
        assert _match_value("test.*", "test123") is True
        assert _match_value("^prefix", "prefix_value") is True
        assert _match_value("suffix$", "value_suffix") is True

    def test_match_value_regex_pattern_no_match(self):
        assert _match_value("^start", "no_start_here") is False

    def test_match_value_invalid_regex_falls_back_to_equality(self):
        assert _match_value("[invalid", "[invalid") is True
        assert _match_value("[invalid", "other") is False

    def test_match_value_list_pattern_matches_any(self):
        assert _match_value(["a", "b", "c"], "b") is True
        assert _match_value(["x", "y"], "z") is False

    def test_match_value_list_with_regex_patterns(self):
        assert _match_value(["^test.*", "^prod.*"], "test_env") is True
        assert _match_value(["^test.*", "^prod.*"], "dev_env") is False

    def test_match_value_non_string_equality(self):
        assert _match_value(42, 42) is True
        assert _match_value(42, 43) is False

    def test_match_value_converts_value_to_string(self):
        assert _match_value("123", 123) is True


class TestMatchAllCriteria:
    def test_match_all_criteria_empty_criteria_matches(self):
        assert _match_all_criteria({}, {"a": 1, "b": 2}) is True

    def test_match_all_criteria_all_match(self):
        criteria = {"type": "s3", "region": "eu-central-1"}
        values = {"type": "s3", "region": "eu-central-1", "extra": "value"}

        assert _match_all_criteria(criteria, values) is True

    def test_match_all_criteria_one_mismatch(self):
        criteria = {"type": "s3", "region": "us-west-2"}
        values = {"type": "s3", "region": "eu-central-1"}

        assert _match_all_criteria(criteria, values) is False

    def test_match_all_criteria_missing_key(self):
        criteria = {"required_key": "value"}
        values = {"other_key": "value"}

        assert _match_all_criteria(criteria, values) is False


class TestRouterSingleton:
    @pytest.fixture(autouse=True)
    def reset_router(self):
        Router.reset()
        yield
        Router.reset()

    def test_is_initialized_returns_false_before_init(self):
        assert Router.is_initialized() is False

    def test_initialize_sets_instance(self):
        config = MagicMock()
        config.repositories = {}
        config.routes = {}
        config.pipelines = {}

        router = Router.initialize(config)

        assert Router.is_initialized() is True
        assert router is Router.get_instance()

    def test_get_instance_raises_before_init(self):
        with pytest.raises(RuntimeError, match="Router not initialized"):
            Router.get_instance()

    def test_reset_clears_singleton(self):
        config = MagicMock()
        config.repositories = {}
        config.routes = {}
        config.pipelines = {}

        Router.initialize(config)
        Router.reset()

        assert Router.is_initialized() is False

    def test_initialize_loads_from_settings_when_config_none(self):
        mock_settings = MagicMock()
        mock_settings.pipeline_configuration.repositories = {}
        mock_settings.pipeline_configuration.routes = {}
        mock_settings.pipeline_configuration.pipelines = {}

        with patch("etl.config.settings.get_settings", return_value=mock_settings):
            Router.initialize(None)

            assert Router.is_initialized() is True


class TestRouterParsing:
    @pytest.fixture(autouse=True)
    def reset_router(self):
        yield
        Router.reset()

    def test_parse_repositories_extracts_type_and_config(self):
        raw = {"my_repo": {"type": "s3", "bucket": "test", "region": "eu-central-1"}}

        result = Router._parse_repositories(raw)

        assert "my_repo" in result
        assert result["my_repo"].type == "s3"
        assert result["my_repo"].config == {"bucket": "test", "region": "eu-central-1"}

    def test_parse_pipelines_creates_pipeline_configs(self):
        raw = {"my_pipeline": {"transforms": ["transform1", "transform2"]}}

        result = Router._parse_pipelines(raw)

        assert "my_pipeline" in result
        assert result["my_pipeline"].transforms == ["transform1", "transform2"]

    def test_parse_routes_with_string_pipeline(self):
        raw = {"my_route": {"match": {"source": "test"}, "pipeline": "my_pipeline", "destinations": {}}}

        result = Router._parse_routes(raw)

        assert result["my_route"].pipeline.name == "my_pipeline"
        assert result["my_route"].pipeline.config == {}

    def test_parse_routes_with_dict_pipeline(self):
        raw = {
            "my_route": {
                "match": {"source": "test"},
                "pipeline": {"name": "my_pipeline", "config": {"key": "value"}},
                "destinations": {},
            }
        }

        result = Router._parse_routes(raw)

        assert result["my_route"].pipeline.name == "my_pipeline"
        assert result["my_route"].pipeline.config == {"key": "value"}

    def test_parse_routes_with_destinations(self):
        raw = {
            "my_route": {
                "match": {},
                "pipeline": "pipeline",
                "destinations": {"output": {"repository": "s3_repo", "path": "/output"}},
            }
        }

        result = Router._parse_routes(raw)

        assert "output" in result["my_route"].destinations
        assert result["my_route"].destinations["output"].repository == "s3_repo"
        assert result["my_route"].destinations["output"].path == "/output"


class TestRouterRepositoryAccess:
    @pytest.fixture
    def router(self):
        repos = {
            "s3_prod": RepositoryConfig(type="s3", config={"bucket": "prod", "region": "eu-central-1"}),
            "s3_dev": RepositoryConfig(type="s3", config={"bucket": "dev", "region": "us-west-2"}),
            "local": RepositoryConfig(type="local", config={"path": "/data"}),
        }
        return Router(repositories=repos, routes={}, pipelines={})

    def test_get_repository_returns_config(self, router):
        result = router.get_repository("s3_prod")

        assert result is not None
        assert result.type == "s3"

    def test_get_repository_returns_none_for_missing(self, router):
        result = router.get_repository("nonexistent")

        assert result is None

    def test_list_repositories_returns_all(self, router):
        result = router.list_repositories()

        assert len(result) == 3
        assert "s3_prod" in result
        assert "local" in result

    def test_find_repositories_by_type(self, router):
        result = router.find_repositories(type="s3")

        assert len(result) == 2
        assert "s3_prod" in result
        assert "s3_dev" in result
        assert "local" not in result

    def test_find_repositories_by_config_field(self, router):
        result = router.find_repositories(region="eu-central-1")

        assert len(result) == 1
        assert "s3_prod" in result


class TestRouterRouteAccess:
    @pytest.fixture
    def router(self):
        routes = {
            "pdf_route": RouteConfig(
                match={"file_type": "pdf", "source": "upload"},
                pipeline=PipelineRef(name="pdf_pipeline"),
                destinations={},
            ),
            "xml_route": RouteConfig(
                match={"file_type": "xml"}, pipeline=PipelineRef(name="xml_pipeline"), destinations={}
            ),
        }
        return Router(repositories={}, routes=routes, pipelines={})

    def test_get_route_returns_config(self, router):
        result = router.get_route("pdf_route")

        assert result is not None
        assert result.pipeline.name == "pdf_pipeline"

    def test_get_route_returns_none_for_missing(self, router):
        result = router.get_route("nonexistent")

        assert result is None

    def test_list_routes_returns_all(self, router):
        result = router.list_routes()

        assert len(result) == 2

    def test_get_routes_by_criteria_matches(self, router):
        result = router.get_routes_by_criteria(file_type="pdf")

        assert len(result) == 1
        assert "pdf_route" in result

    def test_get_routes_by_criteria_multiple_criteria(self, router):
        result = router.get_routes_by_criteria(file_type="pdf", source="upload")

        assert len(result) == 1
        assert "pdf_route" in result

    def test_get_routes_by_criteria_no_match(self, router):
        result = router.get_routes_by_criteria(file_type="csv")

        assert len(result) == 0


class TestRouterPipelineAccess:
    @pytest.fixture
    def router(self):
        pipelines = {
            "pdf_pipeline": PipelineConfig(transforms=["extract", "chunk"]),
            "xml_pipeline": PipelineConfig(transforms=["parse", "validate"]),
        }
        return Router(repositories={}, routes={}, pipelines=pipelines)

    def test_get_pipeline_returns_config(self, router):
        result = router.get_pipeline("pdf_pipeline")

        assert result is not None
        assert result.transforms == ["extract", "chunk"]

    def test_get_pipeline_returns_none_for_missing(self, router):
        result = router.get_pipeline("nonexistent")

        assert result is None

    def test_list_pipelines_returns_all(self, router):
        result = router.list_pipelines()

        assert len(result) == 2


class TestRouterRouteMatching:
    @pytest.fixture
    def router(self):
        routes = {
            "pdf_route": RouteConfig(
                match={"file_type": "pdf"},
                pipeline=PipelineRef(name="pdf_pipeline"),
                destinations={"output": DestinationConfig(repository="s3", path="/pdf")},
            ),
            "xml_route": RouteConfig(
                match={"file_type": "xml"},
                pipeline=PipelineRef(name="xml_pipeline", config={"validate": True}),
                destinations={},
            ),
            "catchall": RouteConfig(match={}, pipeline=PipelineRef(name="default_pipeline"), destinations={}),
        }
        pipelines = {
            "pdf_pipeline": PipelineConfig(transforms=["pdf_extract"]),
            "xml_pipeline": PipelineConfig(transforms=["xml_parse"]),
            "default_pipeline": PipelineConfig(transforms=[]),
        }
        return Router(repositories={}, routes=routes, pipelines=pipelines)

    def test_match_route_returns_first_match(self, router):
        result = router.match_route(file_type="pdf")

        assert result is not None
        assert result.route_name == "pdf_route"
        assert result.pipeline_name == "pdf_pipeline"

    def test_match_route_includes_destinations(self, router):
        result = router.match_route(file_type="pdf")

        assert "output" in result.destinations
        assert result.destinations["output"].path == "/pdf"

    def test_match_route_includes_pipeline_config_override(self, router):
        result = router.match_route(file_type="xml")

        assert result.pipeline_config_override == {"validate": True}

    def test_match_route_returns_none_when_pipeline_missing(self):
        routes = {
            "orphan_route": RouteConfig(
                match={"type": "test"}, pipeline=PipelineRef(name="nonexistent_pipeline"), destinations={}
            )
        }
        router = Router(repositories={}, routes=routes, pipelines={})

        result = router.match_route(type="test")

        assert result is None

    def test_match_route_returns_none_when_no_match(self, router):
        result = router.match_route(file_type="csv", source="unknown")

        assert result.route_name == "catchall"

    def test_match_all_routes_returns_all_matches(self, router):
        result = router.match_all_routes(file_type="pdf")

        route_names = [r.route_name for r in result]
        assert "pdf_route" in route_names
        assert "catchall" in route_names

    def test_match_all_routes_empty_when_no_match(self):
        routes = {
            "specific": RouteConfig(match={"required": "value"}, pipeline=PipelineRef(name="pipeline"), destinations={})
        }
        pipelines = {"pipeline": PipelineConfig(transforms=[])}
        router = Router(repositories={}, routes=routes, pipelines=pipelines)

        result = router.match_all_routes(other="different")

        assert result == []


class TestRouterBatchMatch:
    @pytest.fixture
    def router(self):
        routes = {
            "type_a": RouteConfig(match={"type": "a"}, pipeline=PipelineRef(name="pipeline_a"), destinations={}),
            "type_b": RouteConfig(match={"type": "b"}, pipeline=PipelineRef(name="pipeline_b"), destinations={}),
        }
        pipelines = {
            "pipeline_a": PipelineConfig(transforms=[]),
            "pipeline_b": PipelineConfig(transforms=[]),
        }
        return Router(repositories={}, routes=routes, pipelines=pipelines)

    def test_batch_match_groups_by_route(self, router):
        items = [
            {"type": "a", "id": 1},
            {"type": "b", "id": 2},
            {"type": "a", "id": 3},
        ]

        result = router.batch_match(items)

        assert len(result["type_a"]) == 2
        assert len(result["type_b"]) == 1

    def test_batch_match_skips_unmatched_items(self, router):
        items = [
            {"type": "a", "id": 1},
            {"type": "c", "id": 2},
        ]

        result = router.batch_match(items)

        assert "type_a" in result
        assert len(result) == 1


class TestRouterBuildPipelineConfig:
    def test_build_pipeline_config_structure(self):
        match_result = MatchResult(
            route_name="test_route",
            route_config=RouteConfig(match={}, pipeline=PipelineRef(name="test"), destinations={}),
            pipeline_name="test_pipeline",
            pipeline_config=PipelineConfig(transforms=["t1", "t2"]),
            destinations={"output": DestinationConfig(repository="s3_repo", path="/output")},
        )
        router = Router(repositories={}, routes={}, pipelines={})

        result = router.build_pipeline_config(
            match_result, source_objects=["obj1", "obj2"], source_repository="input_repo"
        )

        assert result["transforms"] == ["t1", "t2"]
        assert result["sources"]["primary"]["repository"] == "input_repo"
        assert result["sources"]["primary"]["objects"] == ["obj1", "obj2"]
        assert result["destinations"]["output"]["repository"] == "s3_repo"
        assert result["destinations"]["output"]["path"] == "/output"


class TestConvenienceFunctions:
    @pytest.fixture(autouse=True)
    def reset_router(self):
        yield
        Router.reset()

    def test_get_router_returns_instance(self):
        config = MagicMock()
        config.repositories = {}
        config.routes = {}
        config.pipelines = {}
        Router.initialize(config)

        result = get_router()

        assert result is Router.get_instance()

    def test_initialize_router_returns_instance(self):
        config = MagicMock()
        config.repositories = {}
        config.routes = {}
        config.pipelines = {}

        result = initialize_router(config)

        assert result is Router.get_instance()


class TestMatchResultDataclass:
    def test_match_result_default_values(self):
        result = MatchResult(
            route_name="test",
            route_config=RouteConfig(match={}, pipeline=PipelineRef(name="p"), destinations={}),
            pipeline_name="pipeline",
            pipeline_config=PipelineConfig(transforms=[]),
        )

        assert result.pipeline_config_override == {}
        assert result.destinations == {}


class TestRouteConfigModels:
    def test_destination_config_default_path(self):
        config = DestinationConfig(repository="repo")

        assert config.path == ""

    def test_pipeline_ref_default_config(self):
        ref = PipelineRef(name="pipeline")

        assert ref.config == {}

    def test_route_config_default_values(self):
        config = RouteConfig(pipeline=PipelineRef(name="p"))

        assert config.match == {}
        assert config.destinations == {}

    def test_pipeline_config_default_transforms(self):
        config = PipelineConfig()

        assert config.transforms == []
