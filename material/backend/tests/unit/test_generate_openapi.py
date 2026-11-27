import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from generate_openapi import (  # type: ignore[import-untyped]  # ty: ignore[unresolved-import]
    generate_openapi_spec,
    rewrite_refs,
)


class TestRewriteRefs:
    def test_rewrites_defs_to_components(self):
        obj = {"$ref": "#/$defs/MessageContent"}
        result = rewrite_refs(obj)
        assert result["$ref"] == "#/components/schemas/MessageContent"

    def test_preserves_non_defs_refs(self):
        obj = {"$ref": "#/components/schemas/ChatInput"}
        result = rewrite_refs(obj)
        assert result["$ref"] == "#/components/schemas/ChatInput"

    def test_handles_nested_objects(self):
        obj = {"properties": {"message": {"$ref": "#/$defs/ChatInputMessage"}}}
        result = rewrite_refs(obj)
        assert result["properties"]["message"]["$ref"] == "#/components/schemas/ChatInputMessage"

    def test_handles_lists(self):
        obj = [{"$ref": "#/$defs/Item1"}, {"$ref": "#/$defs/Item2"}]
        result = rewrite_refs(obj)
        assert result[0]["$ref"] == "#/components/schemas/Item1"
        assert result[1]["$ref"] == "#/components/schemas/Item2"


class TestGenerateOpenAPISpec:
    def test_generates_valid_openapi_structure(self):
        spec = generate_openapi_spec()

        assert "openapi" in spec
        assert spec["openapi"] == "3.1.0"
        assert "info" in spec
        assert "paths" in spec
        assert "components" in spec

    def test_includes_chat_endpoint(self):
        spec = generate_openapi_spec()

        assert "/api/chat" in spec["paths"]
        assert "post" in spec["paths"]["/api/chat"]

    def test_includes_feedback_endpoint(self):
        spec = generate_openapi_spec()

        assert "/api/chat/{session_id}/feedback" in spec["paths"]
        assert "put" in spec["paths"]["/api/chat/{session_id}/feedback"]

    def test_includes_health_endpoint(self):
        spec = generate_openapi_spec()

        assert "/health" in spec["paths"]
        assert "get" in spec["paths"]["/health"]

    def test_excludes_history_endpoint(self):
        """History endpoint removed per RFC 0013 session-security M3."""
        spec = generate_openapi_spec()

        assert "/api/chat/{session_id}/history" not in spec["paths"]

    def test_includes_error_responses(self):
        spec = generate_openapi_spec()

        chat_responses = spec["paths"]["/api/chat"]["post"]["responses"]
        assert "400" in chat_responses
        assert "500" in chat_responses

    def test_includes_all_schemas(self):
        spec = generate_openapi_spec()

        schemas = spec["components"]["schemas"]
        assert "ChatInput" in schemas
        assert "ChatOutput" in schemas
        assert "MessageContent" in schemas
        assert "ErrorResponse" in schemas
        assert "HealthResponse" in schemas

    def test_refs_point_to_components_schemas(self):
        spec = generate_openapi_spec()

        def check_refs(obj, path=""):
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref = obj["$ref"]
                    assert ref.startswith("#/components/schemas/"), f"Invalid ref at {path}: {ref}"
                for k, v in obj.items():
                    check_refs(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    check_refs(item, f"{path}[{i}]")

        check_refs(spec)
