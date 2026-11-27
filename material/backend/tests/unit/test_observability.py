import json
import re
import urllib.error
from email.message import Message
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_observability(monkeypatch):
    """Reset module-level telemetry state and opt into content capture."""
    import backend_orchestrator.observability as obs
    from backend_orchestrator.config import Config

    monkeypatch.setenv("OTEL_INCLUDE_CONTENT", "true")
    Config._instance = None
    obs._tracer_provider = None
    obs._instrumentation_settings = None
    yield
    obs._tracer_provider = None
    obs._instrumentation_settings = None
    Config._instance = None


@pytest.mark.unit
def test_setup_skipped_when_no_host(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_NAME", raising=False)

    from backend_orchestrator.config import Config

    Config._instance = None

    with patch("boto3.client") as mock_boto:
        from backend_orchestrator.observability import setup_langfuse_tracing

        result = setup_langfuse_tracing()

    assert result is None
    mock_boto.assert_not_called()


@pytest.mark.unit
def test_setup_creates_provider_and_sets_global(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("LANGFUSE_SECRET_NAME", "langfuse/dev/lambda-api-keys")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")

    from backend_orchestrator.config import Config

    Config._instance = None

    secret_payload = json.dumps({"publicKey": "pk-lf-test", "secretKey": "sk-lf-test"})
    mock_sm = MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": secret_payload}

    with (
        patch("boto3.client", return_value=mock_sm),
        patch("opentelemetry.trace.set_tracer_provider") as mock_set_provider,
        patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"),
    ):
        import importlib

        from backend_orchestrator import observability

        importlib.reload(observability)
        result = observability.setup_langfuse_tracing()

    assert result is not None
    mock_set_provider.assert_called_once()
    assert observability._tracer_provider is not None
    assert observability._instrumentation_settings is not None


@pytest.mark.unit
def test_setup_sets_langfuse_environment_resource_attribute(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.com")
    monkeypatch.setenv("LANGFUSE_SECRET_NAME", "langfuse/dev/lambda-api-keys")
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("REVIEW_ID", "feature-my-branch")

    from backend_orchestrator.config import Config

    Config._instance = None

    secret_payload = json.dumps({"publicKey": "pk-lf-test", "secretKey": "sk-lf-test"})
    mock_sm = MagicMock()
    mock_sm.get_secret_value.return_value = {"SecretString": secret_payload}

    with (
        patch("boto3.client", return_value=mock_sm),
        patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"),
    ):
        import importlib

        from backend_orchestrator import observability

        importlib.reload(observability)
        observability.setup_langfuse_tracing()

        assert observability._tracer_provider is not None
        resource_attrs = observability._tracer_provider.resource.attributes

    assert resource_attrs.get("langfuse.environment") == "review"
    Config._instance = None

    from backend_orchestrator.observability import flush_traces

    flush_traces()


@pytest.mark.unit
def test_set_langfuse_trace_context_sets_all_attributes():
    from backend_orchestrator.observability import set_langfuse_trace_context

    mock_span = MagicMock()
    set_langfuse_trace_context(
        mock_span,
        session_id="sess-123",
        user_id="user-456",
        input_text="hello",
        model="gpt-oss-120b",
        message_id="msg-789",
        environment="dev",
    )

    calls = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
    assert calls["langfuse.trace.name"] == "Chatbot Request"
    assert calls["langfuse.session.id"] == "sess-123"
    assert calls["langfuse.user.id"] == "user-456"
    assert calls["langfuse.observation.input"] == "hello"
    assert calls["langfuse.trace.metadata.model"] == "gpt-oss-120b"
    assert calls["langfuse.trace.metadata.message_id"] == "msg-789"
    assert calls["langfuse.environment"] == "dev"


@pytest.mark.unit
def test_set_langfuse_trace_output():
    from backend_orchestrator.observability import set_langfuse_trace_output

    mock_span = MagicMock()
    set_langfuse_trace_output(mock_span, "the answer")

    mock_span.set_attribute.assert_called_once_with("langfuse.observation.output", "the answer")


@pytest.mark.unit
def test_langfuse_environment_is_review_when_review_id_set(monkeypatch):
    monkeypatch.setenv("REVIEW_ID", "feature-my-branch")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    from backend_orchestrator.config import Config

    Config._instance = None
    config = Config()
    assert config.langfuse_environment == "review"
    Config._instance = None


@pytest.mark.unit
def test_langfuse_environment_unchanged_when_no_review_id(monkeypatch):
    monkeypatch.delenv("REVIEW_ID", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    from backend_orchestrator.config import Config

    Config._instance = None
    config = Config()
    assert config.langfuse_environment == "dev"
    Config._instance = None


@pytest.mark.unit
def test_set_langfuse_trace_context_sets_tags_when_provided():
    from backend_orchestrator.observability import set_langfuse_trace_context

    mock_span = MagicMock()
    set_langfuse_trace_context(
        mock_span,
        session_id="sess",
        user_id="u",
        input_text="q",
        model="m",
        message_id="id",
        environment="review",
        tags=["review-my-branch"],
    )
    calls = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
    assert calls["langfuse.trace.tags"] == ["review-my-branch"]
    assert calls["langfuse.environment"] == "review"


@pytest.mark.unit
def test_set_langfuse_trace_context_no_tags_attribute_when_none():
    from backend_orchestrator.observability import set_langfuse_trace_context

    mock_span = MagicMock()
    set_langfuse_trace_context(
        mock_span,
        session_id="sess",
        user_id="u",
        input_text="q",
        model="m",
        message_id="id",
        environment="dev",
    )
    attr_names = [call.args[0] for call in mock_span.set_attribute.call_args_list]
    assert "langfuse.trace.tags" not in attr_names


@pytest.mark.unit
def test_set_langfuse_trace_context_sets_experiment_item_attrs_when_id_provided():
    """v4 Experiments contract: item.id + item.root_observation_id (16-char lowercase hex) on root."""
    from backend_orchestrator.observability import set_langfuse_trace_context

    mock_span = MagicMock()
    mock_span.get_span_context.return_value.span_id = 0x1234567890ABCDEF

    set_langfuse_trace_context(
        mock_span,
        session_id="sess",
        user_id="u",
        input_text="q",
        model="m",
        message_id="id",
        environment="dev",
        experiment_item_id="golden-set/row42-formal",
    )
    calls = {call.args[0]: call.args[1] for call in mock_span.set_attribute.call_args_list}
    assert calls["langfuse.experiment.item.id"] == "golden-set/row42-formal"
    assert calls["langfuse.experiment.item.root_observation_id"] == "1234567890abcdef"


@pytest.mark.unit
def test_set_langfuse_trace_context_omits_experiment_item_attrs_when_absent():
    from backend_orchestrator.observability import set_langfuse_trace_context

    mock_span = MagicMock()
    set_langfuse_trace_context(
        mock_span,
        session_id="sess",
        user_id="u",
        input_text="q",
        model="m",
        message_id="id",
        environment="dev",
    )
    attr_names = {call.args[0] for call in mock_span.set_attribute.call_args_list}
    assert "langfuse.experiment.item.id" not in attr_names
    assert "langfuse.experiment.item.root_observation_id" not in attr_names


_HEX = "deadbeefdeadbeefdeadbeefdeadbeef"


def _event(**overrides):
    from backend_orchestrator.observability import ScoreEvent

    defaults = {"trace_id": _HEX, "name": "x", "value": 1, "data_type": "NUMERIC"}
    event: ScoreEvent = {**defaults, **overrides}  # type: ignore[typeddict-item]
    return event


class TestPostLangfuseScores:
    def _payload(self, mock_urlopen) -> dict:
        req = mock_urlopen.call_args.args[0]
        return json.loads(req.data.decode())

    def _body(self, mock_urlopen, idx: int = 0) -> dict:
        return self._payload(mock_urlopen)["batch"][idx]["body"]

    @pytest.fixture
    def _auth(self, monkeypatch):
        import backend_orchestrator.observability as obs

        monkeypatch.setattr(obs, "_langfuse_auth", "ZmFrZTpmYWtl")
        monkeypatch.setattr(obs, "_langfuse_host", "https://langfuse.test")
        monkeypatch.setattr(obs, "_langfuse_environment", "dev")

    @pytest.mark.unit
    def test_numeric_body_shape(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(name="latency", value=0.42, data_type="NUMERIC")])
            assert self._body(mock_urlopen) == {
                "traceId": _HEX,
                "name": "latency",
                "value": 0.42,
                "dataType": "NUMERIC",
                "environment": "dev",
            }

    @pytest.mark.unit
    def test_categorical_body_shape(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(name="user.tonality", value="friendly", data_type="CATEGORICAL")])
            body = self._body(mock_urlopen)
            assert body["dataType"] == "CATEGORICAL"
            assert body["value"] == "friendly"

    @pytest.mark.unit
    def test_boolean_body_shape(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(name="user.thumbs_up", value=1, data_type="BOOLEAN")])
            body = self._body(mock_urlopen)
            assert body["dataType"] == "BOOLEAN"
            assert body["value"] == 1

    @pytest.mark.unit
    def test_text_body_shape(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(name="user.note", value="lgtm", data_type="TEXT")])
            assert self._body(mock_urlopen)["dataType"] == "TEXT"

    @pytest.mark.unit
    def test_endpoint_is_ingestion(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            req = mock_urlopen.call_args.args[0]
            assert req.full_url.endswith("/api/public/ingestion")

    @pytest.mark.unit
    def test_timeout_matches_tight_budget(self, _auth):
        """1.5s budget protects user-facing feedback latency."""
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            assert mock_urlopen.call_args.kwargs["timeout"] == 1.5

    @pytest.mark.unit
    def test_envelope_wraps_body_with_type_and_uuid(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            entry = self._payload(mock_urlopen)["batch"][0]
            assert entry["type"] == "score-create"
            assert re.fullmatch(r"[0-9a-f-]{36}", entry["id"])

    @pytest.mark.unit
    def test_timestamp_format_is_iso8601_z_with_milliseconds(self, _auth):
        """datetime.utcnow().isoformat() would be a naive timestamp v4 silently rejects; pin the format."""
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(), _event()])
            for entry in self._payload(mock_urlopen)["batch"]:
                assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", entry["timestamp"])

    @pytest.mark.unit
    def test_comment_included_when_set(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(value=1, data_type="BOOLEAN", comment="nice")])
            assert self._body(mock_urlopen)["comment"] == "nice"

    @pytest.mark.unit
    def test_comment_absent_when_none(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            assert "comment" not in self._body(mock_urlopen)

    @pytest.mark.unit
    def test_id_included_when_set(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(id="msg-7#thumbs_up")])
            assert self._body(mock_urlopen)["id"] == "msg-7#thumbs_up"

    @pytest.mark.unit
    def test_id_absent_when_none(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            assert "id" not in self._body(mock_urlopen)

    @pytest.mark.unit
    def test_metadata_included_when_set(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        metadata = {"producer": "internal_multi_turn", "scope": "dialog", "schema_version": "v2_en_4plus1"}
        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(metadata=metadata)])
            assert self._body(mock_urlopen)["metadata"] == metadata

    @pytest.mark.unit
    def test_metadata_absent_when_not_set(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            assert "metadata" not in self._body(mock_urlopen)

    @pytest.mark.unit
    def test_batch_contains_multiple_events_with_distinct_ids(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(name="a"), _event(name="b"), _event(name="c")])
            batch = self._payload(mock_urlopen)["batch"]
            assert len(batch) == 3
            assert [e["body"]["name"] for e in batch] == ["a", "b", "c"]
            assert len({e["id"] for e in batch}) == 3

    @pytest.mark.unit
    def test_empty_batch_is_noop(self, _auth):
        """Empty batch contract: no POST, no drop metric, no exception."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen,
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([])
            mock_urlopen.assert_not_called()
            mock_metric.assert_not_called()

    @pytest.mark.unit
    def test_unknown_data_type_raises_atomically(self, _auth):
        """Bad data_type is a developer typo; drop the whole batch to surface it."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen,
            pytest.raises(ValueError, match="invalid Langfuse score data_type"),
        ):
            post_langfuse_scores([_event(name="good"), _event(data_type="CORRECTION")])
        mock_urlopen.assert_not_called()

    @pytest.mark.unit
    def test_early_return_when_auth_missing(self, monkeypatch):
        import backend_orchestrator.observability as obs
        from backend_orchestrator.observability import post_langfuse_scores

        monkeypatch.setattr(obs, "_langfuse_auth", None)
        monkeypatch.setattr(obs, "_langfuse_host", "https://langfuse.test")
        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            post_langfuse_scores([_event()])
            mock_urlopen.assert_not_called()

    @pytest.mark.unit
    def test_session_score_sends_session_id_and_no_trace_id(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        event = _event(session_id="s-42")
        del event["trace_id"]
        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([event])
            body = self._body(mock_urlopen)
            assert body["sessionId"] == "s-42"
            assert "traceId" not in body

    @pytest.mark.unit
    def test_dashed_trace_id_is_normalized_to_undashed_hex(self, _auth):
        """Legacy DynamoDB rows carry dashed UUIDs; strip them so Langfuse matches (#885)."""
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([
                _event(trace_id="deadbeef-dead-beef-dead-beefdeadbeef", value=1, data_type="BOOLEAN")
            ])
            assert self._body(mock_urlopen)["traceId"] == _HEX

    @pytest.mark.unit
    def test_malformed_trace_id_warns_but_still_posts(self, _auth):
        """Non-W3C trace_id logs a warning but the batch still goes out."""
        from backend_orchestrator import observability
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen,
            patch.object(observability.logger, "warning") as mock_warn,
        ):
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event(trace_id="not-hex")])
            mock_urlopen.assert_called_once()
            mock_warn.assert_called_once()
            assert "W3C hex" in mock_warn.call_args.args[0]

    @pytest.mark.unit
    def test_environment_included_in_every_shape(self, _auth):
        """v4 scores need `environment` in each body; Langfuse does not inherit it from the trace (#889)."""
        from backend_orchestrator.observability import post_langfuse_scores

        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([
                _event(value=0.42, data_type="NUMERIC"),
                _event(value="friendly", data_type="CATEGORICAL"),
                _event(value=1, data_type="BOOLEAN"),
                _event(value="lgtm", data_type="TEXT"),
            ])
            for entry in self._payload(mock_urlopen)["batch"]:
                assert entry["body"]["environment"] == "dev"

    @pytest.mark.unit
    def test_environment_absent_when_setup_skipped(self, monkeypatch):
        """If setup_langfuse_tracing didn't run, skip the field rather than send `None`."""
        import backend_orchestrator.observability as obs
        from backend_orchestrator.observability import post_langfuse_scores

        monkeypatch.setattr(obs, "_langfuse_auth", "ZmFrZTpmYWtl")
        monkeypatch.setattr(obs, "_langfuse_host", "https://langfuse.test")
        monkeypatch.setattr(obs, "_langfuse_environment", None)
        with patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            req = mock_urlopen.call_args.args[0]
            payload = json.loads(req.data.decode())
            assert "environment" not in payload["batch"][0]["body"]


class TestLangfuseScoreDroppedMetric:
    """Drop metric is the alarm signal for a Langfuse outage."""

    @pytest.fixture
    def _auth(self, monkeypatch):
        import backend_orchestrator.observability as obs

        monkeypatch.setattr(obs, "_langfuse_auth", "ZmFrZTpmYWtl")
        monkeypatch.setattr(obs, "_langfuse_host", "https://langfuse.test")
        monkeypatch.setattr(obs, "_langfuse_environment", "dev")

    def _assert_dropped(self, mock_metric, count: int, mode: str) -> None:
        from aws_lambda_powertools.metrics import MetricUnit

        mock_metric.assert_called_once()
        kwargs = mock_metric.call_args.kwargs
        assert kwargs["name"] == "LangfuseScoreDropped"
        assert kwargs["unit"] == MetricUnit.Count
        assert kwargs["value"] == count
        assert kwargs["namespace"] == "Renate/Backend"
        instance = mock_metric.return_value.__enter__.return_value
        dim_calls = {call.kwargs["name"]: call.kwargs["value"] for call in instance.add_dimension.call_args_list}
        assert dim_calls == {"Environment": "dev", "FailureMode": mode}

    @pytest.mark.unit
    def test_drop_metric_emitted_on_timeout(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=TimeoutError("read timed out"),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event()])
            self._assert_dropped(mock_metric, count=1, mode="timeout")

    @pytest.mark.unit
    def test_drop_metric_emitted_on_connect_timeout_wrapped_in_urlerror(self, _auth):
        """Urllib wraps connect-timeouts in URLError(reason=TimeoutError(...))."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=urllib.error.URLError(TimeoutError("connect timeout")),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event()])
            self._assert_dropped(mock_metric, count=1, mode="timeout")

    @pytest.mark.unit
    def test_drop_metric_emitted_on_network_error(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=OSError("ECONNREFUSED"),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event()])
            self._assert_dropped(mock_metric, count=1, mode="network")

    @pytest.mark.unit
    def test_drop_metric_emitted_on_5xx(self, _auth):
        """5xx must be attributed to Langfuse (http_5xx), not a network blip."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    url="https://langfuse.test/api/public/ingestion",
                    code=503,
                    msg="Service Unavailable",
                    hdrs=Message(),
                    fp=None,
                ),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event()])
            self._assert_dropped(mock_metric, count=1, mode="http_5xx")

    @pytest.mark.unit
    def test_drop_metric_emitted_on_4xx(self, _auth):
        """4xx (auth drift, malformed body) must separate from 5xx so alarms can distinguish causes."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=urllib.error.HTTPError(
                    url="https://langfuse.test/api/public/ingestion",
                    code=401,
                    msg="Unauthorized",
                    hdrs=Message(),
                    fp=None,
                ),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event()])
            self._assert_dropped(mock_metric, count=1, mode="http_4xx")

    @pytest.mark.unit
    def test_drop_metric_value_counts_all_events_in_batch(self, _auth):
        """A failed batch of N drops N scores; the metric must reflect that."""
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch(
                "backend_orchestrator.observability.urllib.request.urlopen",
                side_effect=TimeoutError("read timed out"),
            ),
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            post_langfuse_scores([_event(name="a"), _event(name="b"), _event(name="c")])
            self._assert_dropped(mock_metric, count=3, mode="timeout")

    @pytest.mark.unit
    def test_no_drop_metric_on_success(self, _auth):
        from backend_orchestrator.observability import post_langfuse_scores

        with (
            patch("backend_orchestrator.observability.urllib.request.urlopen") as mock_urlopen,
            patch("backend_orchestrator.observability.single_metric") as mock_metric,
        ):
            mock_urlopen.return_value.__enter__.return_value.status = 207
            post_langfuse_scores([_event()])
            mock_metric.assert_not_called()
