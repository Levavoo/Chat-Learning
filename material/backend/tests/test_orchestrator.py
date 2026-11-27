from backend_orchestrator.validation import extract_message_text


class TestMessageParsing:
    def test_parse_frontend_message_format(self):
        body = {
            "conversation_id": "test-session-123",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "Hello Renate"}],
                "parentMessageId": "",
            },
            "botId": "",
            "continueGenerate": False,
            "enableReasoning": False,
        }

        message = extract_message_text(body)
        assert message == "Hello Renate"

    def test_parse_empty_content_list(self):
        body = {"message": {"role": "user", "content": []}, "conversation_id": "test"}
        message = extract_message_text(body)
        assert message == ""

    def test_parse_string_message_fallback(self):
        body = {"message": "Direct message string", "conversation_id": "test"}
        message = extract_message_text(body)
        assert message == "Direct message string"

    def test_parse_missing_message_field(self):
        body = {"conversation_id": "test"}
        message = extract_message_text(body)
        assert message == ""

    def test_parse_multiple_content_items(self):
        """Only the first content item is used."""
        body = {
            "message": {
                "content": [
                    {"contentType": "text", "body": "First message"},
                    {"contentType": "text", "body": "Second message"},
                ]
            }
        }
        message = extract_message_text(body)
        assert message == "First message"

    def test_parse_missing_body_in_content(self):
        body = {"message": {"content": [{"contentType": "text"}]}}
        message = extract_message_text(body)
        assert message == ""


class TestIntegration:
    def test_full_request_parsing(self):
        request_body = {
            "conversation_id": "conv-123",
            "message": {
                "role": "user",
                "content": [{"contentType": "text", "body": "What is my pension?"}],
                "model": "claude-v3.5-sonnet",
                "parentMessageId": "msg-001",
            },
            "botId": "bot-456",
            "continueGenerate": False,
            "enableReasoning": True,
        }

        message_text = extract_message_text(request_body)
        session_id = request_body.get("conversation_id", "")
        bot_id = request_body.get("botId", "")
        enable_reasoning = request_body.get("enableReasoning", False)

        assert message_text == "What is my pension?"
        assert session_id == "conv-123"
        assert bot_id == "bot-456"
        assert enable_reasoning is True

    def test_minimal_valid_request(self):
        request_body = {
            "conversation_id": "test",
            "message": {"content": [{"contentType": "text", "body": "hi"}]},
        }

        message_text = extract_message_text(request_body)
        session_id = request_body.get("conversation_id", "")

        assert message_text == "hi"
        assert session_id == "test"
