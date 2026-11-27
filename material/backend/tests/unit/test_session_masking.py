from backend_orchestrator.utils.session_masking import (
    mask_message_id,
    mask_session_id,
    sanitize_error_message,
)


class TestMaskSessionId:
    def test_long_id_masked_to_prefix_plus_ellipsis(self):
        assert mask_session_id("abc12345-1234-5678-9abc-def012345678") == "abc12345..."

    def test_exactly_eight_chars(self):
        assert mask_session_id("12345678") == "12345678..."

    def test_short_id_still_gets_ellipsis(self):
        assert mask_session_id("short") == "short..."

    def test_none_returns_empty(self):
        assert mask_session_id(None) == ""

    def test_empty_returns_empty(self):
        assert mask_session_id("") == ""


class TestMaskMessageId:
    def test_frontend_format_masks_prefix_keeps_uuid(self):
        assert mask_message_id("abc12345-1234-5678-9abc-def012345678#uuid-xyz") == "abc12345...#uuid-xyz"

    def test_no_hash_falls_back_to_session_masking(self):
        assert mask_message_id("abc12345-1234") == "abc12345..."

    def test_none_returns_empty(self):
        assert mask_message_id(None) == ""

    def test_empty_returns_empty(self):
        assert mask_message_id("") == ""

    def test_empty_prefix_before_hash(self):
        assert mask_message_id("#uuid-xyz") == "#uuid-xyz"

    def test_session_id_with_embedded_hash_still_masked(self):
        """review-env namespacing can embed "#"; rpartition folds everything before the last "#" into the prefix."""
        assert mask_message_id("review/branch#sess-abc-123#uuid-xyz") == "review/b...#uuid-xyz"


class TestSanitizeErrorMessage:
    def test_long_id_replaced_with_masked_prefix(self):
        sid = "abc12345-1234-5678-9abc-def012345678"
        result = sanitize_error_message(f"bad session {sid} rejected", sid)
        assert sid not in result
        assert "abc12345..." in result

    def test_short_id_collapses_to_static_message(self):
        assert sanitize_error_message("bad session sess7 rejected", "sess7") == "Bad request"

    def test_exactly_eight_char_id_collapses_to_static_message(self):
        """8-char ids fit inside mask_session_id's prefix window, so collapse instead of mask."""
        assert sanitize_error_message("bad session abc12345 rejected", "abc12345") == "Bad request"

    def test_missing_id_returns_message_unchanged(self):
        assert sanitize_error_message("bad request", "abc12345-1234-5678-9abc-def012345678") == "bad request"

    def test_none_session_id_returns_message_unchanged(self):
        assert sanitize_error_message("bad request", None) == "bad request"

    def test_empty_session_id_returns_message_unchanged(self):
        assert sanitize_error_message("bad request", "") == "bad request"

    def test_non_string_session_id_returns_message_unchanged(self):
        """Runtime safety net for callers that forget to coerce non-str ids."""
        bad_values: list = [42, {"x": 1}, [1, 2]]
        for value in bad_values:
            assert sanitize_error_message("bad request", value) == "bad request"
