from unittest.mock import MagicMock, patch

import pytest

from backend_orchestrator.controllers.session_controller import SessionController


class TestSessionController:
    @pytest.fixture
    def mock_conversation_store(self):
        store = MagicMock()
        store.delete_session.return_value = 5
        return store

    @pytest.fixture
    def controller(self, mock_conversation_store):
        return SessionController(mock_conversation_store)

    @pytest.fixture
    def mock_app(self):
        return MagicMock()

    def test_returns_ok_on_successful_deletion(self, controller, mock_app):
        result = controller.handle_delete_session(mock_app, "abc12345-1234-5678-9abc-def012345678")
        assert result == {"status": "ok"}

    def test_calls_delete_session_on_store(self, controller, mock_app, mock_conversation_store):
        controller.handle_delete_session(mock_app, "abc12345-1234-5678-9abc-def012345678")
        mock_conversation_store.delete_session.assert_called_once_with("abc12345-1234-5678-9abc-def012345678")

    def test_rejects_invalid_uuid_format(self, controller, mock_app):
        from aws_lambda_powertools.event_handler.exceptions import BadRequestError

        with pytest.raises(BadRequestError, match="Invalid conversation ID format"):
            controller.handle_delete_session(mock_app, "not-a-uuid")

    def test_rejects_empty_string(self, controller, mock_app):
        from aws_lambda_powertools.event_handler.exceptions import BadRequestError

        with pytest.raises(BadRequestError, match="Invalid conversation ID format"):
            controller.handle_delete_session(mock_app, "")

    def test_rejects_uuid_without_hyphens(self, controller, mock_app):
        from aws_lambda_powertools.event_handler.exceptions import BadRequestError

        with pytest.raises(BadRequestError, match="Invalid conversation ID format"):
            controller.handle_delete_session(mock_app, "abc123451234567899bcdef012345678")

    def test_accepts_uppercase_uuid(self, controller, mock_app, mock_conversation_store):
        result = controller.handle_delete_session(mock_app, "ABC12345-1234-5678-9ABC-DEF012345678")
        assert result == {"status": "ok"}
        mock_conversation_store.delete_session.assert_called_once()

    def test_returns_ok_even_when_session_not_found(self, controller, mock_app, mock_conversation_store):
        mock_conversation_store.delete_session.return_value = 0
        result = controller.handle_delete_session(mock_app, "abc12345-1234-5678-9abc-def012345678")
        assert result == {"status": "ok"}

    def test_returns_ok_on_store_exception(self, controller, mock_app, mock_conversation_store):
        """DELETE is best-effort: a store exception still returns 200."""
        mock_conversation_store.delete_session.side_effect = Exception("DynamoDB is down")

        with patch("backend_orchestrator.controllers.session_controller.logger") as mock_logger:
            result = controller.handle_delete_session(mock_app, "abc12345-1234-5678-9abc-def012345678")

        assert result == {"status": "ok"}
        mock_logger.exception.assert_called_once()

    def test_logs_only_masked_session_id(self, controller, mock_app):
        with patch("backend_orchestrator.controllers.session_controller.logger") as mock_logger:
            controller.handle_delete_session(mock_app, "abc12345-1234-5678-9abc-def012345678")

        call_kwargs = mock_logger.info.call_args.kwargs
        assert call_kwargs["extra"]["session_id"] == "abc12345..."

    def test_does_not_log_full_conversation_id(self, controller, mock_app):
        full_id = "abc12345-1234-5678-9abc-def012345678"
        with patch("backend_orchestrator.controllers.session_controller.logger") as mock_logger:
            controller.handle_delete_session(mock_app, full_id)

        for call in mock_logger.method_calls:
            call_str = str(call)
            assert full_id not in call_str
