"""Unit tests for ConsentController."""

from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.controllers.consent_controller import ConsentController


class TestConsentController:
    @pytest.fixture
    def mock_logs_client(self):
        client = MagicMock()
        client.exceptions.ResourceAlreadyExistsException = type("ResourceAlreadyExistsException", (Exception,), {})
        return client

    @pytest.fixture
    def controller(self, mock_logs_client):
        return ConsentController(
            log_group_name="/renate/dev/consent-log",
            logs_client=mock_logs_client,
        )

    @pytest.fixture
    def mock_app(self):
        app = MagicMock()
        app.current_event.request_context.identity.source_ip = "203.0.113.42"
        return app

    def test_returns_ok(self, controller, mock_app):
        result = controller.handle_consent_request(mock_app)
        assert result == {"status": "ok"}

    def test_writes_structured_log_entry(self, controller, mock_app, mock_logs_client):
        controller.handle_consent_request(mock_app)

        mock_logs_client.put_log_events.assert_called_once()
        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        assert call_kwargs["logGroupName"] == "/renate/dev/consent-log"
        assert call_kwargs["logStreamName"].startswith("consent/")

        import json

        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert message["ip"] == "203.0.113.42"
        assert message["consent"] is True
        assert message["service"] == "consent"
        assert "timestamp" in message

    def test_creates_log_stream_daily(self, controller, mock_app, mock_logs_client):
        controller.handle_consent_request(mock_app)

        mock_logs_client.create_log_stream.assert_called_once()
        call_kwargs = mock_logs_client.create_log_stream.call_args.kwargs
        assert call_kwargs["logGroupName"] == "/renate/dev/consent-log"
        assert call_kwargs["logStreamName"].startswith("consent/")
        date_part = call_kwargs["logStreamName"].split("/")[1]
        assert len(date_part) == 10  # YYYY-MM-DD

    def test_handles_existing_log_stream(self, controller, mock_app, mock_logs_client):
        mock_logs_client.create_log_stream.side_effect = mock_logs_client.exceptions.ResourceAlreadyExistsException(
            "already exists"
        )

        result = controller.handle_consent_request(mock_app)
        assert result == {"status": "ok"}
        mock_logs_client.put_log_events.assert_called_once()

    def test_missing_ip_defaults_to_unknown(self, controller, mock_logs_client):
        app = MagicMock()
        app.current_event.request_context.identity.source_ip = None

        controller.handle_consent_request(app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert message["ip"] == "unknown"

    def test_missing_ip_attribute_error(self, controller, mock_logs_client):
        app = MagicMock()
        app.current_event.request_context = MagicMock(spec=["identity"])
        app.current_event.request_context.identity = object()  # real object with no source_ip

        controller.handle_consent_request(app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert message["ip"] == "unknown"

    def test_cloudwatch_write_failure_still_returns_ok(self, controller, mock_app, mock_logs_client):
        mock_logs_client.put_log_events.side_effect = Exception("CW is down")

        with patch("backend_orchestrator.controllers.consent_controller.logger") as mock_logger:
            result = controller.handle_consent_request(mock_app)

        assert result == {"status": "ok"}
        mock_logger.exception.assert_called_once()

    def test_no_session_or_user_id_in_log(self, controller, mock_app, mock_logs_client):
        """Consent log must NOT contain session or user identifiers without body."""
        controller.handle_consent_request(mock_app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert "user_id" not in message
        assert "conversationId" not in message

    def test_includes_session_id_when_provided_in_body(self, controller, mock_logs_client):
        app = MagicMock()
        app.current_event.request_context.identity.source_ip = "10.0.0.1"
        app.current_event.json_body = {"sessionId": "abc12345-1234-5678-9abc-def012345678"}

        controller.handle_consent_request(app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert message["sessionId"] == "abc12345-1234-5678-9abc-def012345678"

    def test_no_session_id_when_body_is_none(self, controller, mock_app, mock_logs_client):
        mock_app.current_event.json_body = None

        controller.handle_consent_request(mock_app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert "sessionId" not in message

    def test_no_session_id_when_body_is_empty_dict(self, controller, mock_app, mock_logs_client):
        mock_app.current_event.json_body = {}

        controller.handle_consent_request(mock_app)

        import json

        call_kwargs = mock_logs_client.put_log_events.call_args.kwargs
        message = json.loads(call_kwargs["logEvents"][0]["message"])
        assert "sessionId" not in message

    def test_handles_malformed_body_gracefully(self, controller, mock_logs_client):
        app = MagicMock()
        app.current_event.request_context.identity.source_ip = "10.0.0.1"
        app.current_event.json_body = "not a dict"

        result = controller.handle_consent_request(app)
        assert result == {"status": "ok"}
