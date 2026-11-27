from backend_orchestrator.validators.message_validator import validate_message_length


class TestMessageLengthValidation:
    def test_empty_message_rejected(self):
        is_valid, error = validate_message_length("")
        assert not is_valid
        assert error == "Message is required"

    def test_message_too_long_rejected(self):
        is_valid, error = validate_message_length("A" * 10001)
        assert not is_valid
        assert error is not None
        assert "exceeds maximum length" in error

    def test_normal_message_accepted(self):
        is_valid, error = validate_message_length("Wie hoch ist meine Rente mit 67 Jahren?")
        assert is_valid
        assert error is None


class TestWordLengthValidation:
    """max_word_length: reject messages containing a single word > 1000 chars."""

    def test_single_word_over_limit_rejected(self):
        long_word = "A" * 1001
        is_valid, error = validate_message_length(long_word)
        assert not is_valid
        assert error is not None
        assert "word exceeding maximum length" in error

    def test_word_at_exact_limit_accepted(self):
        word_at_limit = "A" * 1000
        is_valid, error = validate_message_length(word_at_limit)
        assert is_valid
        assert error is None

    def test_long_word_among_short_words_rejected(self):
        message = "Hallo " + ("B" * 1001) + " wie geht es"
        is_valid, error = validate_message_length(message)
        assert not is_valid
        assert error is not None
        assert "word exceeding maximum length" in error

    def test_many_short_words_accepted(self):
        message = " ".join(["hallo"] * 500)
        is_valid, error = validate_message_length(message)
        assert is_valid
        assert error is None


class TestSpecialCharRatioValidation:
    """max_special_char_ratio: reject messages with > 50% special characters."""

    def test_high_special_char_ratio_rejected(self):
        message = "!" * 20 + "ab"
        is_valid, error = validate_message_length(message)
        assert not is_valid
        assert error is not None
        assert "special character ratio" in error

    def test_low_special_char_ratio_accepted(self):
        message = "Wie hoch ist meine Rente, wenn ich mit 67 Jahren in Rente gehe?"
        is_valid, error = validate_message_length(message)
        assert is_valid
        assert error is None

    def test_ratio_at_exact_boundary_accepted(self):
        """Rejection is on '>', so a message at exactly 0.5 is accepted."""
        message = "!" * 10 + "a" * 10
        is_valid, error = validate_message_length(message)
        assert is_valid
        assert error is None

    def test_unicode_letters_not_counted_as_special(self):
        message = "Grundrentenzuschlag für Rentnerinnen und Rentner mit Wohnsitz in Übersee"
        is_valid, error = validate_message_length(message)
        assert is_valid
        assert error is None

    def test_whitespace_not_counted_as_special(self):
        message = "hallo " * 10
        is_valid, error = validate_message_length(message)
        assert is_valid
        assert error is None
