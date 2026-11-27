"""Unit tests for ChatController."""

import json
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, InternalServerError, ServiceError

from backend_orchestrator.controllers.chat_controller import (
    _TRACE_TAGS_MAX_COUNT,
    _TRACE_TAGS_MAX_LEN,
    ChatController,
    _resolve_trace_tags,
)
from backend_orchestrator.repositories.conversation import HistoryReadError
from backend_orchestrator.services.chat_service import ConversationLimitReachedError
from backend_orchestrator.utils.session_masking import mask_session_id

_FAKE_TRACE_ID_INT = 0xDEADBEEFDEADBEEFDEADBEEFDEADBEEF
_FAKE_TRACE_HEX = "deadbeefdeadbeefdeadbeefdeadbeef"
# Chat root span id (16-char hex). All fixtures set this alongside trace_id so
# the controller's format_span_id call sees a real int, not a MagicMock.
_FAKE_SPAN_ID_INT = 0xCAFEBABECAFEBABE


class TestChatController:
    """Tests for ChatController class."""

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    @pytest.fixture
    def mock_service(self):
        """Mock ChatService."""
        return MagicMock()

    @pytest.fixture
    def mock_app(self):
        """Mock APIGatewayRestResolver."""
        app = MagicMock()
        app.current_event.json_body = {"message": "Hello", "conversation_id": "sess-123"}
        app.current_event.request_context.authorizer = {"claims": {"sub": "user-123", "cognito:username": "testuser"}}
        app.current_event.request_context.request_time_epoch = 1234567890
        return app

    def test_handle_chat_request_success(self, mock_service, mock_app):
        """Test successful chat request handling."""
        # Setup service return
        mock_service.process_message.return_value = {
            "response_text": "Response",
            "used_chunks": [],
            "message_id": "sess-123#uuid",
        }
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",  # Model inside message (API contract)
                "messageId": "sess-123#uuid",
            },
            "conversation_id": "sess-123",
        }

        controller = ChatController(mock_service)

        # We need to patch build_chat_response since it's imported in controller
        with patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build:
            mock_build.return_value = {"statusCode": 200, "body": "{}"}

            controller.handle_chat_request(mock_app)

            # Verify extraction logic - controller uses positional args
            mock_service.process_message.assert_called_once_with(
                "Hello", "sess-123", 1234567890, "sess-123#uuid", trace_id=_FAKE_TRACE_HEX
            )

            mock_build.assert_called_with(
                session_id="sess-123",
                response_text="Response",
                used_chunks=[],
                request_time_epoch=1234567890,
                message_id="sess-123#uuid",
                trace_id=_FAKE_TRACE_HEX,
                all_sources=None,
                root_span_id=None,
                eval_mode=False,
            )

    def test_handle_chat_request_validation_error(self, mock_service, mock_app):
        """Test handling of validation error from service."""
        mock_service.process_message.side_effect = ValueError("Invalid input")
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",  # Model inside message (API contract)
                "messageId": "sess-123#uuid",
            },
            "conversation_id": "sess-123",
        }

        controller = ChatController(mock_service)

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(mock_app)

        assert exc_info.value.msg == "Invalid input"

    def test_handle_chat_request_unexpected_error(self, mock_service, mock_app):
        """Test handling of unexpected error."""
        mock_service.process_message.side_effect = Exception("Crash")
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",  # Model inside message (API contract)
                "messageId": "sess-123#uuid",
            },
            "conversation_id": "sess-123",
        }

        controller = ChatController(mock_service)

        with pytest.raises(InternalServerError) as exc_info:
            controller.handle_chat_request(mock_app)

        assert exc_info.value.msg == "Internal server error"

    @pytest.mark.parametrize(
        ("service_error", "status", "msg"),
        [
            (ConversationLimitReachedError(), 409, "conversation_limit_reached"),
            (HistoryReadError("boom"), 503, "Conversation history unavailable"),
        ],
    )
    def test_handle_chat_request_maps_limit_and_read_errors(self, mock_service, mock_app, service_error, status, msg):
        """#992: own status for the limit, 503 for a failed history read (not the generic 500)."""
        mock_service.process_message.side_effect = service_error
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "messageId": "sess-123#uuid",
            },
            "conversation_id": "sess-123",
        }

        controller = ChatController(mock_service)

        with pytest.raises(ServiceError) as exc_info:
            controller.handle_chat_request(mock_app)

        assert exc_info.value.status_code == status
        assert exc_info.value.msg == msg

    def test_handle_chat_request_camel_case_conversation_id(self, mock_service, mock_app):
        """Test that camelCase conversationId from frontend is correctly extracted."""
        mock_service.process_message.return_value = {
            "response_text": "Response",
            "used_chunks": [],
            "message_id": "camel-sess#uuid",
        }
        mock_app.current_event.json_body = {
            "conversationId": "camel-sess",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                "messageId": "camel-sess#uuid",
            },
        }

        controller = ChatController(mock_service)
        with patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build:
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            controller.handle_chat_request(mock_app)

            mock_service.process_message.assert_called_once_with(
                "Hello", "camel-sess", 1234567890, "camel-sess#uuid", trace_id=_FAKE_TRACE_HEX
            )

    def test_handle_chat_request_camel_case_takes_precedence(self, mock_service, mock_app):
        """Test that conversationId takes precedence over conversation_id when both present."""
        mock_service.process_message.return_value = {
            "response_text": "Response",
            "used_chunks": [],
            "message_id": "msg-1",
        }
        mock_app.current_event.json_body = {
            "conversationId": "camel-wins",
            "conversation_id": "snake-loses",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }

        controller = ChatController(mock_service)
        with patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build:
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            controller.handle_chat_request(mock_app)

            mock_service.process_message.assert_called_once_with(
                "Hello", "camel-wins", 1234567890, "msg-1", trace_id=_FAKE_TRACE_HEX
            )

    def test_handle_chat_request_formats_trace_id_as_w3c_hex(self, mock_otel_tracer, mock_service, mock_app):
        """trace_id passed to the service must be 32-char lowercase hex (W3C), never a dashed UUID.

        A plain fixture-vs-fixture equality check re-passes if someone reintroduces dashing
        with a matching fixture value. Pin the invariant: use a non-palindromic OTel int
        (0x1) that produces an unambiguously undashed string and assert against the W3C regex.
        """
        import re

        span = mock_otel_tracer.start_as_current_span.return_value.__enter__.return_value
        span.get_span_context.return_value.trace_id = 0x1
        span.get_span_context.return_value.span_id = 0x1

        mock_service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [],
            "message_id": "sess-123#uuid",
        }
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                "messageId": "sess-123#uuid",
            },
            "conversation_id": "sess-123",
        }

        controller = ChatController(mock_service)
        with patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build:
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            controller.handle_chat_request(mock_app)

        passed_trace_id = mock_service.process_message.call_args.kwargs["trace_id"]
        assert passed_trace_id == "00000000000000000000000000000001"
        assert re.fullmatch(r"[0-9a-f]{32}", passed_trace_id)

    def test_handle_chat_request_falls_back_to_cognito_when_no_conversation_id(self, mock_service, mock_app):
        """Test fallback to Cognito sub when neither conversationId nor conversation_id is provided."""
        mock_service.process_message.return_value = {
            "response_text": "Response",
            "used_chunks": [],
            "message_id": "msg-1",
        }
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }

        controller = ChatController(mock_service)
        with patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build:
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            controller.handle_chat_request(mock_app)

            # Should fall back to Cognito sub "user-123" from mock_app fixture
            mock_service.process_message.assert_called_once_with(
                "Hello", "user-123", 1234567890, "msg-1", trace_id=_FAKE_TRACE_HEX
            )

    def test_handle_chat_request_without_message_id_raises_400(self, mock_service, mock_app):
        """Chat requests without messageId must surface a real HTTP 400 (#882).

        Previously the envelope dict was silently serialized as HTTP 200.
        """
        mock_app.current_event.json_body = {
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                # No messageId at any nesting level.
            },
            "conversationId": "sess-123",
        }

        controller = ChatController(mock_service)

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(mock_app)

        assert exc_info.value.msg == "message_id is required"

    def test_handle_feedback_request_without_session_id_raises_400(self, mock_service):
        """Empty session_id reaches the controller through the URL path and must raise 400 (#882)."""
        controller = ChatController(mock_service)
        app = MagicMock()
        app.current_event.json_body = {"messageId": "m-1", "feedback": {"helpfulness": "GOOD"}}
        app.current_event.request_context.authorizer = None

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_feedback_request(app, "")

        assert exc_info.value.msg == "session_id is required"

    def test_handle_feedback_request_without_message_id_raises_400(self, mock_service):
        """Feedback body missing messageId must surface a real 400 instead of a 200-wrapped envelope (#882)."""
        controller = ChatController(mock_service)
        app = MagicMock()
        app.current_event.json_body = {"feedback": {"helpfulness": "GOOD"}}
        app.current_event.request_context.authorizer = None

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_feedback_request(app, "sess-123")

        assert exc_info.value.msg == "message_id is required"

    def test_handle_feedback_request_without_feedback_raises_400(self, mock_service):
        """Feedback body with only ids (no feedback payload) must raise 400 (#882)."""
        controller = ChatController(mock_service)
        app = MagicMock()
        app.current_event.json_body = {"messageId": "m-1"}
        app.current_event.request_context.authorizer = None

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_feedback_request(app, "sess-123")

        assert exc_info.value.msg == "feedback is required"

    def test_handle_feedback_request_unexpected_error_raises_500(self, mock_service):
        """Downstream failures in store_feedback must emit a real HTTP 500 (#882)."""
        mock_service.store_feedback.side_effect = Exception("DynamoDB unavailable")
        controller = ChatController(mock_service)
        app = MagicMock()
        app.current_event.json_body = {"messageId": "m-1", "feedback": {"helpfulness": "GOOD"}}
        app.current_event.request_context.authorizer = None

        with pytest.raises(InternalServerError) as exc_info:
            controller.handle_feedback_request(app, "sess-123")

        assert exc_info.value.msg == "Internal server error"

    def test_extract_user_context(self, mock_service):
        """Test extraction of user context."""
        controller = ChatController(mock_service)

        # Case 1: Full context
        event = MagicMock()
        event.request_context.authorizer = {"claims": {"sub": "u1", "cognito:username": "name1"}}
        uid, uname = controller._extract_user_context(event)
        assert uid == "u1"
        assert uname == "name1"

        # Case 2: No authorizer
        event.request_context.authorizer = None
        uid, uname = controller._extract_user_context(event)
        assert uid is None
        assert uname is None


class TestChatControllerSessionMasking:
    """Session-ID must be masked in every log record emitted by the controller (#482 / RFC M4)."""

    _FULL_SESSION = "sess-full-value-12345"
    _FULL_MESSAGE = "sess-full-value-12345#uuid-abcdef"

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    def _mock_app(self):
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": self._FULL_SESSION,
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": self._FULL_MESSAGE,
            },
        }
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}
        app.current_event.request_context.request_time_epoch = 1
        return app

    def test_chat_request_never_logs_full_session_id_or_message_id(self):
        service = MagicMock()
        service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [],
            "message_id": self._FULL_MESSAGE,
        }
        controller = ChatController(service)

        with (
            patch("backend_orchestrator.controllers.chat_controller.logger") as mock_logger,
            patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build,
        ):
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            controller.handle_chat_request(self._mock_app())

        # The full session-id must not appear in ANY log call — args, kwargs, or extra values.
        for call in mock_logger.method_calls:
            call_str = str(call)
            assert self._FULL_SESSION not in call_str, f"full session_id leaked into log call: {call_str}"

    def test_feedback_request_never_logs_full_session_id_or_message_id(self):
        service = MagicMock()
        service.store_feedback.return_value = True
        controller = ChatController(service)
        app = MagicMock()
        app.current_event.json_body = {"messageId": self._FULL_MESSAGE, "feedback": {"helpfulness": "GOOD"}}
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}

        with patch("backend_orchestrator.controllers.chat_controller.logger") as mock_logger:
            controller.handle_feedback_request(app, self._FULL_SESSION)

        for call in mock_logger.method_calls:
            call_str = str(call)
            assert self._FULL_SESSION not in call_str, f"full session_id leaked into log call: {call_str}"

    def test_capture_method_decorators_disable_response_capture(self):
        # X-Ray subsegment metadata would otherwise serialize the return value (which
        # contains session_id via build_chat_response). Guard the whole chain: the inner
        # controller AND the outer route handlers/lambda handler in orchestrator.py must
        # all disable response capture, or the outermost segment still leaks the body.
        import inspect

        from backend_orchestrator import orchestrator
        from backend_orchestrator.controllers import chat_controller

        controller_src = inspect.getsource(chat_controller)
        # Both controller-level decorators must be parameterized with capture_response=False.
        assert controller_src.count("@tracer.capture_method(capture_response=False)") == 2
        # And there must be no bare @tracer.capture_method left in the controller.
        assert "@tracer.capture_method\n" not in controller_src

        orchestrator_src = inspect.getsource(orchestrator)
        # The route handlers all pass through the response dict; every capture_method +
        # the outer capture_lambda_handler must disable response capture.
        assert "@tracer.capture_method\n" not in orchestrator_src
        assert "@tracer.capture_lambda_handler\n" not in orchestrator_src
        assert "@tracer.capture_lambda_handler(capture_response=False)" in orchestrator_src


class _RaisingJsonBody:
    """Fixture double whose `json_body` property raises, mimicking Powertools' JSON decode failure."""

    @property
    def json_body(self):
        raise ValueError("malformed json")


class TestChatControllerErrorResponseSessionIdLeakage:
    """Error responses must never contain the full session-ID (#483 / RFC M6)."""

    _FULL_SESSION = "sess-full-value-12345"
    _FULL_MESSAGE = "sess-full-value-12345#uuid-abcdef"

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    def _mock_app(self):
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": self._FULL_SESSION,
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": self._FULL_MESSAGE,
            },
        }
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}
        app.current_event.request_context.request_time_epoch = 1
        return app

    def test_chat_400_error_body_does_not_contain_full_session_id(self):
        service = MagicMock()
        service.process_message.side_effect = ValueError(f"Bad session {self._FULL_SESSION} rejected")
        controller = ChatController(service)

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(self._mock_app())

        assert self._FULL_SESSION not in exc_info.value.msg
        # Masked prefix must be present — proves the sanitizer ran, not that some unrelated path stripped the id.
        assert mask_session_id(self._FULL_SESSION) in exc_info.value.msg

    def test_chat_500_error_body_does_not_contain_full_session_id(self):
        service = MagicMock()
        service.process_message.side_effect = Exception(f"Bedrock refused {self._FULL_SESSION}")
        controller = ChatController(service)

        with pytest.raises(InternalServerError) as exc_info:
            controller.handle_chat_request(self._mock_app())

        assert exc_info.value.msg == "Internal server error"
        assert self._FULL_SESSION not in json.dumps({"error": exc_info.value.msg})

    def test_chat_400_json_decode_error_before_session_id_is_safe(self):
        controller = ChatController(MagicMock())
        app = MagicMock()
        app.current_event = _RaisingJsonBody()

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(app)

        assert exc_info.value.msg == "malformed json"

    def test_chat_400_null_conversation_id_on_anonymous_request_is_safe(self):
        # Anonymous request (no cognito claims) with `conversationId: null` used to leave session_id
        # as None; the sanitizer would then hit `len(None)` and raise TypeError from inside the
        # ValueError handler — uncaught by the sibling except Exception, propagating a 5xx.
        service = MagicMock()
        service.process_message.side_effect = ValueError("bad request")
        controller = ChatController(service)
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": None,
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": self._FULL_MESSAGE,
            },
        }
        app.current_event.request_context.authorizer = None
        app.current_event.request_context.request_time_epoch = 1

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(app)

        assert exc_info.value.msg == "bad request"

    def test_chat_400_non_string_conversation_id_is_safe(self):
        # A client-supplied conversationId of a non-string type must not crash the sanitizer via
        # `len(non_str)` or `non_str in str` (both TypeErrors) before the mask can be applied.
        service = MagicMock()
        service.process_message.side_effect = ValueError("bad request")
        controller = ChatController(service)
        for bad_value in (42, {"nested": 1}, [1, 2], True):
            app = MagicMock()
            app.current_event.json_body = {
                "conversationId": bad_value,
                "message": {
                    "role": "user",
                    "content": [{"contentType": "text", "body": "Hi"}],
                    "model": "test-model",
                    "messageId": self._FULL_MESSAGE,
                },
            }
            app.current_event.request_context.authorizer = None
            app.current_event.request_context.request_time_epoch = 1

            with pytest.raises(BadRequestError) as exc_info:
                controller.handle_chat_request(app)

            assert exc_info.value.msg == "bad request", f"failed for {bad_value!r}"

    def test_chat_400_short_conversation_id_is_still_masked(self):
        # No length gate on the sanitizer: even a short caller-supplied session id must be masked
        # (unconditional M6 invariant). Short-id substring corruption of unrelated words in the
        # error message is acceptable — the acceptance criterion trumps UX for pathological input.
        short_session = "sess7"
        service = MagicMock()
        service.process_message.side_effect = ValueError(f"invalid session {short_session} rejected")
        controller = ChatController(service)
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": short_session,
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": f"{short_session}#uuid",
            },
        }
        app.current_event.request_context.authorizer = None
        app.current_event.request_context.request_time_epoch = 1

        with pytest.raises(BadRequestError) as exc_info:
            controller.handle_chat_request(app)

        assert short_session not in exc_info.value.msg
        assert exc_info.value.msg == "Bad request"


def _fake_app(header_value: str | None, header_name: str = "X-Langfuse-Trace-Tags") -> MagicMock:
    """Fake APIGatewayRestResolver whose ``current_event.headers`` carries one header."""
    app = MagicMock()
    app.current_event.headers = {header_name: header_value} if header_value is not None else {}
    return app


class TestResolveTraceTags:
    """Shape of the X-Langfuse-Trace-Tags header → langfuse.trace.tags pipeline.

    Pure-function tests: exercise _resolve_trace_tags directly so the merge,
    whitespace, length-cap, and count-cap rules get their own failures.
    """

    def test_absent_header_and_no_review_tag_yields_none(self):
        assert _resolve_trace_tags(_fake_app(None), review_tag="") is None

    def test_absent_header_falls_back_to_review_tag(self):
        assert _resolve_trace_tags(_fake_app(None), review_tag="review-foo") == ["review-foo"]

    def test_header_tags_pass_through_without_review_tag(self):
        tags = _resolve_trace_tags(_fake_app("golden-run,env:dev,run:local-1"), review_tag="")
        assert tags == ["golden-run", "env:dev", "run:local-1"]

    def test_review_tag_merges_with_header_tags_in_order(self):
        tags = _resolve_trace_tags(_fake_app("golden-run,env:dev"), review_tag="review-foo")
        assert tags == ["review-foo", "golden-run", "env:dev"]

    def test_whitespace_and_empty_tokens_are_filtered(self):
        tags = _resolve_trace_tags(_fake_app("a,, ,b, c "), review_tag="")
        assert tags == ["a", "b", "c"]

    def test_tag_count_capped_at_max(self):
        """A 20-tag header must land as the first 10 tags.

        A client that spams tags should not corrupt a shared surface — the
        cap is the backstop that keeps the Traces view's tag filter usable.
        """
        header = ",".join(f"t{i}" for i in range(_TRACE_TAGS_MAX_COUNT * 2))
        tags = _resolve_trace_tags(_fake_app(header), review_tag="")
        assert tags == [f"t{i}" for i in range(_TRACE_TAGS_MAX_COUNT)]

    def test_tag_longer_than_max_len_is_dropped(self):
        """Oversize tags are dropped silently.

        Truncating would corrupt the semantic value (e.g. a run_name) with
        no way for the reader to tell.
        """
        long_tag = "x" * (_TRACE_TAGS_MAX_LEN + 1)
        tags = _resolve_trace_tags(_fake_app(f"a,{long_tag},b"), review_tag="")
        assert tags == ["a", "b"]

    def test_tag_exactly_max_len_is_kept(self):
        boundary = "x" * _TRACE_TAGS_MAX_LEN
        tags = _resolve_trace_tags(_fake_app(f"a,{boundary},b"), review_tag="")
        assert tags == ["a", boundary, "b"]

    def test_header_lookup_is_case_insensitive(self):
        """Case-fold must still resolve a lowercased client header.

        REST API Gateway preserves client-supplied header casing — our own
        case-fold must still resolve a lowercased client header.
        """
        app = _fake_app("a,b", header_name="x-langfuse-trace-tags")
        assert _resolve_trace_tags(app, review_tag="") == ["a", "b"]


class TestChatControllerPassesTagsToObservability:
    """End-to-end: a header on the request lands in set_langfuse_trace_context(tags=...)."""

    _FAKE_TRACE_ID_INT = 0xDEADBEEFDEADBEEFDEADBEEFDEADBEEF

    @pytest.fixture
    def controller(self):
        """Patch _otel_tracer + build_chat_response + set_langfuse_trace_context.

        Yields ``(ChatController, mock_set_langfuse_trace_context)`` so each
        test can assert the tags kwarg on the mocked helper. The otel_tracer
        plumbing matches the other test classes in this file.
        """
        service = MagicMock()
        service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [],
            "message_id": "msg-1",
        }
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = self._FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer),
            patch(
                "backend_orchestrator.controllers.chat_controller.build_chat_response",
                return_value={"statusCode": 200, "body": "{}"},
            ),
            patch(
                "backend_orchestrator.controllers.chat_controller.set_langfuse_trace_context",
            ) as mock_set_tags,
        ):
            yield ChatController(service), mock_set_tags

    def _app_with_header(self, header_value: str | None) -> MagicMock:
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": "sess-1",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}
        app.current_event.request_context.request_time_epoch = 1
        app.current_event.headers = {"X-Langfuse-Trace-Tags": header_value} if header_value is not None else {}
        return app

    def test_header_tags_land_in_set_langfuse_trace_context(self, controller):
        ctrl, mock_set_tags = controller
        app = self._app_with_header("golden-run,env:dev,run:local-1")

        # langfuse_review_tag defaults to "" so only header tags should surface.
        with patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg:
            mock_cfg.return_value.langfuse_review_tag = ""
            mock_cfg.return_value.langfuse_environment = "dev"
            ctrl.handle_chat_request(app)

        kwargs = mock_set_tags.call_args.kwargs
        assert kwargs["tags"] == ["golden-run", "env:dev", "run:local-1"]

    def test_no_header_and_no_review_tag_passes_none(self, controller):
        ctrl, mock_set_tags = controller
        app = self._app_with_header(None)

        with patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg:
            mock_cfg.return_value.langfuse_review_tag = ""
            mock_cfg.return_value.langfuse_environment = "dev"
            ctrl.handle_chat_request(app)

        assert mock_set_tags.call_args.kwargs["tags"] is None

    def test_review_tag_without_header_is_unchanged_behaviour(self, controller):
        ctrl, mock_set_tags = controller
        app = self._app_with_header(None)

        with patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg:
            mock_cfg.return_value.langfuse_review_tag = "review-foo"
            mock_cfg.return_value.langfuse_environment = "review"
            ctrl.handle_chat_request(app)

        assert mock_set_tags.call_args.kwargs["tags"] == ["review-foo"]


class TestFeedbackRequestValidation:
    """The feedback handler validates the body and routes it to the right store method."""

    @staticmethod
    def _app(body: dict) -> MagicMock:
        app = MagicMock()
        app.current_event.json_body = body
        app.current_event.request_context.authorizer = {"claims": {"sub": "user-123", "cognito:username": "tester"}}
        return app

    def test_invalid_rating_raises_422(self):
        service = MagicMock()
        body = {"messageId": "m-1", "isFinalFeedback": True, "goodToRecommend": "Ja"}

        with pytest.raises(ServiceError) as exc_info:
            ChatController(service).handle_feedback_request(self._app(body), "sess-123")

        assert exc_info.value.status_code == 422
        assert "goodToRecommend" in exc_info.value.msg
        service.store_rating.assert_not_called()

    def test_dialog_rating_without_message_id_is_stored(self):
        service = MagicMock()
        service.store_rating.return_value = True
        body = {"isMultiturn": True, "usedScenario": 2, "dialogueSkills": "Yes", "goalAchievement": "No"}

        result = ChatController(service).handle_feedback_request(self._app(body), "sess-123")

        assert result == {"success": True}
        kwargs = service.store_rating.call_args.kwargs
        assert kwargs["message_id"] is None
        assert kwargs["rating"].scope == "dialog"
        assert kwargs["user_id"] == "user-123"

    def test_three_button_body_is_stored_unchanged(self):
        service = MagicMock()
        service.store_feedback.return_value = True
        feedback = {
            "comment": None,
            "helpfulness": "BAD",
            "isFinalFeedback": False,
            "isFreeUserTest": False,
            "isMultiturn": False,
            "isSingleturn": False,
        }

        ChatController(service).handle_feedback_request(self._app({"messageId": "m-1", **feedback}), "sess-123")

        service.store_feedback.assert_called_once_with(
            session_id="sess-123", message_id="m-1", feedback={**feedback, "user_id": "user-123"}
        )
        service.store_rating.assert_not_called()


class TestEvalModeForwarding:
    """`X-Renate-Eval-Mode` must gate forwarding ``all_sources`` to the response.

    Without the header, ``build_chat_response`` must receive ``all_sources=None``
    even when the service dict carries ``all_sources`` (which it always does).
    """

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    def _mk_app(self, header_value: str | None):
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": "sess-1",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}
        app.current_event.request_context.request_time_epoch = 1
        app.current_event.headers = {"X-Renate-Eval-Mode": header_value} if header_value is not None else {}
        return app

    def _run(self, header_value: str | None, environment: str = "dev"):
        service = MagicMock()
        service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [{"content": "cited", "contentType": "text", "rank": 1}],
            "all_sources": [
                {"content": "cited", "contentType": "text", "rank": 1},
                {"content": "uncited", "contentType": "text", "rank": 2},
            ],
            "message_id": "msg-1",
        }
        with (
            patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build,
            patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg,
        ):
            mock_cfg.return_value.langfuse_review_tag = ""
            mock_cfg.return_value.langfuse_environment = environment
            mock_cfg.return_value.environment = environment
            mock_cfg.return_value.bedrock_model_id = "test-model"
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            ChatController(service).handle_chat_request(self._mk_app(header_value))
        return mock_build.call_args.kwargs

    def test_header_absent_drops_all_sources(self):
        """Default callers never see ``all_sources`` — payload stays unchanged."""
        kwargs = self._run(None)
        assert kwargs["all_sources"] is None
        assert kwargs["eval_mode"] is False

    @pytest.mark.parametrize("truthy", ["1", "true", "True", "YES", "on"])
    def test_header_truthy_forwards_all_sources(self, truthy):
        """Any truthy value opts the caller into the full retrieved set."""
        kwargs = self._run(truthy)
        assert kwargs["all_sources"] is not None
        assert len(kwargs["all_sources"]) == 2
        assert kwargs["eval_mode"] is True

    @pytest.mark.parametrize("falsy", ["0", "false", "no", "off", ""])
    def test_header_falsy_still_drops_all_sources(self, falsy):
        """A header with a falsy value is treated as absent."""
        kwargs = self._run(falsy)
        assert kwargs["all_sources"] is None
        assert kwargs["eval_mode"] is False

    @pytest.mark.parametrize("truthy", ["1", "true", "yes", "on"])
    def test_header_ignored_in_prod_environment(self, truthy):
        """Prod never surfaces eval payloads, regardless of header.

        The eval job runs against DEV/QA only — a prod chat response must
        never leak ``all_sources`` or internal retrieval signals.
        """
        kwargs = self._run(truthy, environment="prod")
        assert kwargs["all_sources"] is None
        assert kwargs["eval_mode"] is False


class TestExperimentContextForwarding:
    """The X-Renate-Experiment-* headers must land as Langfuse v4 attrs.

    Experiment-level: three keys ride on baggage (so the baggage span processor
    stamps them on every child span). Item-level: ``experiment_item_id`` is
    passed to ``set_langfuse_trace_context`` which sets it on the root span
    alongside ``langfuse.experiment.item.root_observation_id``.
    """

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = 0xDEADBEEFCAFEBABE
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    _ALL_HEADERS: ClassVar[dict[str, str]] = {
        "X-Renate-Eval-Mode": "1",
        "X-Renate-Experiment-Id": "exp-uuid-1",
        "X-Renate-Experiment-Name": "pipeline-14359",
        "X-Renate-Experiment-Dataset-Id": "cmvapcnpv0001qm2vuuifx5uj",
        "X-Renate-Experiment-Item-Id": "golden-set/row42-formal",
    }

    def _mk_app(self, headers: dict[str, str]):
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": "sess-1",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }
        app.current_event.request_context.authorizer = {"claims": {"sub": "u", "cognito:username": "n"}}
        app.current_event.request_context.request_time_epoch = 1
        app.current_event.headers = headers
        return app

    def _run(self, headers: dict[str, str], environment: str = "dev"):
        service = MagicMock()
        service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [],
            "message_id": "msg-1",
        }
        with (
            patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build,
            patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg,
            patch("backend_orchestrator.controllers.chat_controller.set_langfuse_trace_context") as mock_set,
            patch("backend_orchestrator.controllers.chat_controller.baggage") as mock_baggage,
            patch("backend_orchestrator.controllers.chat_controller.context") as mock_context,
        ):
            mock_cfg.return_value.langfuse_review_tag = ""
            mock_cfg.return_value.langfuse_environment = environment
            mock_cfg.return_value.environment = environment
            mock_cfg.return_value.bedrock_model_id = "test-model"
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            # Thread the baggage context through so the controller's chain lines up
            mock_baggage.set_baggage.side_effect = lambda key, value, context=None: {**(context or {}), key: value}
            mock_context.attach.return_value = "token"
            ChatController(service).handle_chat_request(self._mk_app(headers))
        return {
            "set_langfuse": mock_set.call_args.kwargs,
            "baggage_calls": [c.args for c in mock_baggage.set_baggage.call_args_list],
        }

    def test_all_four_headers_populate_baggage_and_root_attr(self):
        """Happy path: baggage carries experiment-level and item-level keys.

        Three experiment-level + two item-level keys; root span gets the item id
        via set_langfuse_trace_context.
        """
        out = self._run(self._ALL_HEADERS)
        baggage_pairs = {args[0]: args[1] for args in out["baggage_calls"]}
        assert baggage_pairs["langfuse.experiment.id"] == "exp-uuid-1"
        assert baggage_pairs["langfuse.experiment.name"] == "pipeline-14359"
        assert baggage_pairs["langfuse.experiment.dataset.id"] == "cmvapcnpv0001qm2vuuifx5uj"
        assert baggage_pairs["langfuse.experiment.item.id"] == "golden-set/row42-formal"
        # root_observation_id = root span's own 16-char hex spanId (fixture = 0xDEADBEEFCAFEBABE)
        assert baggage_pairs["langfuse.experiment.item.root_observation_id"] == "deadbeefcafebabe"
        assert out["set_langfuse"]["experiment_item_id"] == "golden-set/row42-formal"

    def test_prod_environment_ignores_experiment_headers(self):
        """Hard-off in prod: the eval-mode gate suppresses experiment attrs.

        Even when every header is present, nothing experiment-y lands on
        the trace — neither experiment-level nor item-level baggage.
        """
        out = self._run(self._ALL_HEADERS, environment="prod")
        baggage_keys = {args[0] for args in out["baggage_calls"]}
        assert "langfuse.experiment.id" not in baggage_keys
        assert "langfuse.experiment.name" not in baggage_keys
        assert "langfuse.experiment.dataset.id" not in baggage_keys
        assert "langfuse.experiment.item.id" not in baggage_keys
        assert "langfuse.experiment.item.root_observation_id" not in baggage_keys
        assert out["set_langfuse"]["experiment_item_id"] is None

    def test_missing_eval_mode_header_ignores_experiment_headers(self):
        """The eval-mode gate is the single trigger.

        Experiment headers without X-Renate-Eval-Mode are a no-op.
        """
        headers = {k: v for k, v in self._ALL_HEADERS.items() if k != "X-Renate-Eval-Mode"}
        out = self._run(headers)
        baggage_keys = {args[0] for args in out["baggage_calls"]}
        assert "langfuse.experiment.id" not in baggage_keys
        assert out["set_langfuse"]["experiment_item_id"] is None

    @pytest.mark.parametrize(
        "omit",
        [
            "X-Renate-Experiment-Id",
            "X-Renate-Experiment-Name",
            "X-Renate-Experiment-Dataset-Id",
            "X-Renate-Experiment-Item-Id",
        ],
    )
    def test_partial_experiment_headers_treated_as_absent(self, omit):
        """Partial experiment context is treated as absent.

        A half-tagged trace confuses the Experiments UI more than an untagged
        one. Refuse, don't best-effort.
        """
        headers = {k: v for k, v in self._ALL_HEADERS.items() if k != omit}
        out = self._run(headers)
        baggage_keys = {args[0] for args in out["baggage_calls"]}
        assert "langfuse.experiment.id" not in baggage_keys
        assert "langfuse.experiment.name" not in baggage_keys
        assert "langfuse.experiment.dataset.id" not in baggage_keys
        assert out["set_langfuse"]["experiment_item_id"] is None

    def test_experiment_header_lookup_is_case_insensitive(self):
        """Experiment header lookup is case-insensitive.

        REST API Gateway preserves client-supplied header casing — accept
        lowercased client headers too, matching _lookup_header_ci's contract.
        """
        headers = {k.lower(): v for k, v in self._ALL_HEADERS.items()}
        out = self._run(headers)
        baggage_pairs = {args[0]: args[1] for args in out["baggage_calls"]}
        assert baggage_pairs["langfuse.experiment.id"] == "exp-uuid-1"
        assert out["set_langfuse"]["experiment_item_id"] == "golden-set/row42-formal"


class TestLangfuseBaggageKeysContract:
    """LANGFUSE_BAGGAGE_KEYS must cover every Langfuse experiment/trace baggage key.

    Every key the controller writes must be declared — otherwise the span processor won't stamp them
    onto child spans and the Experiments UI loses the context on model/tool
    spans. Covers both experiment-level (set before span start) and item-level
    (set after span start with the root's own span id) keys per v4 docs §3.
    """

    def test_experiment_and_item_keys_are_declared_for_baggage_propagation(self):
        from backend_orchestrator.otel_propagation import LANGFUSE_BAGGAGE_KEYS

        for key in (
            "langfuse.session.id",
            "langfuse.user.id",
            "langfuse.experiment.id",
            "langfuse.experiment.name",
            "langfuse.experiment.dataset.id",
            "langfuse.experiment.item.id",
            "langfuse.experiment.item.root_observation_id",
        ):
            assert key in LANGFUSE_BAGGAGE_KEYS


class TestUserIdOverride:
    """``X-Renate-User-Id`` must swap in a synthetic marker for ``user.id``.

    Golden-run sends e.g. ``synthetic:eval:pipeline-14390`` so dashboards and
    the user.helpfulness correlation workbench can filter real users from
    automated runs (renate/scheduled/evaluation#9). Hard-off in prod via
    ``_eval_mode_enabled``.
    """

    @pytest.fixture(autouse=True)
    def mock_otel_tracer(self):
        mock_span = MagicMock()
        mock_span.get_span_context.return_value.trace_id = _FAKE_TRACE_ID_INT
        mock_span.get_span_context.return_value.span_id = _FAKE_SPAN_ID_INT
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
        with patch("backend_orchestrator.controllers.chat_controller._otel_tracer", mock_tracer):
            yield mock_tracer

    _COGNITO_SUB = "cognito-sub-aaaa"
    _SYNTHETIC_MARKER = "synthetic:eval:pipeline-14390"

    def _mk_app(self, headers: dict[str, str]):
        app = MagicMock()
        app.current_event.json_body = {
            "conversationId": "sess-1",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hi"}],
                "model": "test-model",
                "messageId": "msg-1",
            },
        }
        app.current_event.request_context.authorizer = {
            "claims": {"sub": self._COGNITO_SUB, "cognito:username": "svc-user"}
        }
        app.current_event.request_context.request_time_epoch = 1
        app.current_event.headers = headers
        return app

    def _run(self, headers: dict[str, str], environment: str = "dev"):
        service = MagicMock()
        service.process_message.return_value = {
            "response_text": "r",
            "used_chunks": [],
            "message_id": "msg-1",
        }
        with (
            patch("backend_orchestrator.controllers.chat_controller.build_chat_response") as mock_build,
            patch("backend_orchestrator.controllers.chat_controller.get_config") as mock_cfg,
            patch("backend_orchestrator.controllers.chat_controller.set_langfuse_trace_context") as mock_set,
            patch("backend_orchestrator.controllers.chat_controller.baggage") as mock_baggage,
            patch("backend_orchestrator.controllers.chat_controller.context") as mock_context,
        ):
            mock_cfg.return_value.langfuse_review_tag = ""
            mock_cfg.return_value.langfuse_environment = environment
            mock_cfg.return_value.environment = environment
            mock_cfg.return_value.bedrock_model_id = "test-model"
            mock_build.return_value = {"statusCode": 200, "body": "{}"}
            mock_baggage.set_baggage.side_effect = lambda key, value, context=None: {**(context or {}), key: value}
            mock_context.attach.return_value = "token"
            ChatController(service).handle_chat_request(self._mk_app(headers))
        return {
            "set_langfuse": mock_set.call_args.kwargs,
            "baggage_calls": [c.args for c in mock_baggage.set_baggage.call_args_list],
        }

    def test_header_overrides_cognito_sub_when_eval_mode_on(self):
        out = self._run({"X-Renate-Eval-Mode": "1", "X-Renate-User-Id": self._SYNTHETIC_MARKER})
        baggage_pairs = {args[0]: args[1] for args in out["baggage_calls"]}
        assert out["set_langfuse"]["user_id"] == self._SYNTHETIC_MARKER
        assert baggage_pairs["langfuse.user.id"] == self._SYNTHETIC_MARKER

    def test_absent_header_keeps_cognito_sub(self):
        """Eval mode on but no override header → Cognito sub still wins.

        Guards against the override silently blanking user_id.
        """
        out = self._run({"X-Renate-Eval-Mode": "1"})
        baggage_pairs = {args[0]: args[1] for args in out["baggage_calls"]}
        assert out["set_langfuse"]["user_id"] == self._COGNITO_SUB
        assert baggage_pairs["langfuse.user.id"] == self._COGNITO_SUB

    def test_prod_environment_ignores_override_header(self):
        """Hard-off in prod via ``_eval_mode_enabled``.

        A prod caller sending the header must not be able to spoof a different
        user_id onto a real trace.
        """
        out = self._run(
            {"X-Renate-Eval-Mode": "1", "X-Renate-User-Id": self._SYNTHETIC_MARKER},
            environment="prod",
        )
        assert out["set_langfuse"]["user_id"] == self._COGNITO_SUB

    def test_missing_eval_mode_header_ignores_override(self):
        """The eval-mode gate is the single trigger.

        The override header alone is a no-op (same contract as the experiment
        headers).
        """
        out = self._run({"X-Renate-User-Id": self._SYNTHETIC_MARKER})
        assert out["set_langfuse"]["user_id"] == self._COGNITO_SUB

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_whitespace_only_header_treated_as_absent(self, blank: str):
        """Defensive: a blank header must not blank user_id on the trace.

        It reads as "no override", not "override to empty".
        """
        out = self._run({"X-Renate-Eval-Mode": "1", "X-Renate-User-Id": blank})
        assert out["set_langfuse"]["user_id"] == self._COGNITO_SUB

    def test_header_lookup_is_case_insensitive(self):
        """REST API Gateway preserves client-supplied casing.

        Accept lowercased client headers too, matching the rest of the controller.
        """
        out = self._run({"x-renate-eval-mode": "1", "x-renate-user-id": self._SYNTHETIC_MARKER})
        assert out["set_langfuse"]["user_id"] == self._SYNTHETIC_MARKER
