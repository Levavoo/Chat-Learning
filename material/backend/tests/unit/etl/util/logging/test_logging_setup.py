
import logging
from unittest.mock import MagicMock, patch

import pytest

import etl.util.logging_setup as logging_setup_module
from etl.util.logging_setup import (
    COLOR_MAP,
    COLOR_RESET,
    ColoredFormatter,
    get_logger,
    set_global_loglevel,
)


class TestColoredFormatter:

    def test_formt_debug_level_uses_cyan_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.DEBUG,
            pathname="test.py",
            lineno=10,
            msg="debug message",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert COLOR_MAP["DEBUG"] in result
        assert "debug message" in result

    def test_formt_info_level_uses_green_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=20,
            msg="info message",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert COLOR_MAP["INFO"] in result
        assert "info message" in result

    def test_formt_warning_level_uses_yellow_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=30,
            msg="warning message",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert COLOR_MAP["WARNING"] in result
        assert "warning message" in result

    def test_formt_error_level_uses_red_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=40,
            msg="error message",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert COLOR_MAP["ERROR"] in result
        assert "error message" in result

    def test_formt_critical_level_uses_background_red_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.CRITICAL,
            pathname="test.py",
            lineno=50,
            msg="critical message",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert COLOR_MAP["CRITICAL"] in result
        assert "critical message" in result

    def test_formt_includes_logger_name_with_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="my.custom.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert "my.custom.logger" in result
        assert COLOR_MAP["NAME"] in result

    def test_formt_includes_file_location_with_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/path/to/myfile.py",
            lineno=42,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert "myfile.py:42" in result
        assert COLOR_MAP["LOCATION"] in result

    def test_formt_includes_asctime(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 15:30:45"

        result = formatter.formt(record)

        assert "2026-01-12 15:30:45" in result

    def test_formt_includes_color_reset_codes(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="test",
            args=(),
            exc_info=None,
        )
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert result.count(COLOR_RESET) >= 3

    def test_formt_unknown_level_uses_reset_color(self):
        formatter = ColoredFormatter()
        record = logging.LogRecord(
            name="test",
            level=25,
            pathname="test.py",
            lineno=10,
            msg="custom level",
            args=(),
            exc_info=None,
        )
        record.levelname = "CUSTOM"
        record.asctime = "2026-01-12 10:00:00"

        result = formatter.formt(record)

        assert "CUSTOM" in result
        assert "custom level" in result


class TestGetLogger:

    @pytest.fixture(autouse=True)
    def cleanup_loggers(self):
        yield
        logging_setup_module._loggers.clear()

    def test_get_logger_creates_new_logger_with_name(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = False
            mock_get_logger.return_value = mock_logger

            result = get_logger("test.new.logger")

            mock_get_logger.assert_called_with("test.new.logger")
            assert result is mock_logger

    def test_get_logger_returns_cached_logger_on_second_call(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = False
            mock_get_logger.return_value = mock_logger

            logger1 = get_logger("test.cached.new")
            logger2 = get_logger("test.cached.new")

            assert logger1 is logger2
            mock_get_logger.assert_called_once()

    def test_get_logger_without_name_uses_module_name(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = False
            mock_get_logger.return_value = mock_logger

            get_logger(None)

            mock_get_logger.assert_called_with("etl.util.logging_setup")

    def test_get_logger_sets_debug_level(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = False
            mock_get_logger.return_value = mock_logger

            get_logger("test.level.new")

            mock_logger.setLevel.assert_called_with(logging.DEBUG)

    def test_get_logger_adds_stream_handler_when_no_handlers(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:  # noqa: SIM117
            with patch("etl.util.logging_setup.logging.StreamHandler") as mock_stream_handler:
                with patch("etl.util.logging_setup.logging.FileHandler"):
                    mock_logger = MagicMock()
                    mock_logger.hasHandlers.return_value = False
                    mock_get_logger.return_value = mock_logger

                    get_logger("test.stream.new")

                    mock_stream_handler.assert_called_once()
                    assert mock_logger.addHandler.call_count >= 1

    def test_get_logger_adds_file_handler_when_no_handlers(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:  # noqa: SIM117
            with patch("etl.util.logging_setup.logging.StreamHandler"):
                with patch("etl.util.logging_setup.logging.FileHandler") as mock_file_handler:
                    mock_logger = MagicMock()
                    mock_logger.hasHandlers.return_value = False
                    mock_get_logger.return_value = mock_logger

                    get_logger("test.file.new")

                    mock_file_handler.assert_called_once_with("etl.log")

    def test_get_logger_uses_colored_formatter_for_stream_handler(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = False
            mock_get_logger.return_value = mock_logger
            mock_stream_handler = MagicMock()

            with patch("etl.util.logging_setup.logging.StreamHandler", return_value=mock_stream_handler):  # noqa: SIM117
                with patch("etl.util.logging_setup.logging.FileHandler"):
                    get_logger("test.formatter.new")

                    call_args = mock_stream_handler.setFormatter.call_args
                    assert isinstance(call_args[0][0], ColoredFormatter)

    def test_get_logger_skips_handlers_when_already_present(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_logger.hasHandlers.return_value = True
            mock_get_logger.return_value = mock_logger

            with patch("etl.util.logging_setup.logging.StreamHandler") as mock_sh:  # noqa: SIM117
                with patch("etl.util.logging_setup.logging.FileHandler") as mock_fh:
                    get_logger("test.skip.handlers")

                    mock_sh.assert_not_called()
                    mock_fh.assert_not_called()

    def test_get_logger_different_names_create_different_loggers(self):
        with patch("etl.util.logging_setup.logging.getLogger") as mock_get_logger:
            mock_logger1 = MagicMock()
            mock_logger1.hasHandlers.return_value = False
            mock_logger2 = MagicMock()
            mock_logger2.hasHandlers.return_value = False
            mock_get_logger.side_effect = [mock_logger1, mock_logger2]

            logger1 = get_logger("test.one.new")
            logger2 = get_logger("test.two.new")

            assert logger1 is not logger2


class TestSetGlobalLoglevel:

    @pytest.fixture(autouse=True)
    def cleanup_loggers(self):
        yield
        logging_setup_module._loggers.clear()

    def test_set_global_loglevel_iterates_over_cached_loggers(self):
        mock_logger1 = MagicMock()
        mock_logger2 = MagicMock()
        logging_setup_module._loggers["logger1"] = mock_logger1
        logging_setup_module._loggers["logger2"] = mock_logger2

        set_global_loglevel(logging.WARNING)

        mock_logger1.setLevel.assert_called_once()
        mock_logger2.setLevel.assert_called_once()

    def test_set_global_loglevel_with_no_loggers_does_not_raise(self):
        logging_setup_module._loggers.clear()

        set_global_loglevel(logging.INFO)


class TestColorConstants:

    def test_color_reset_is_escape_sequence(self):
        assert COLOR_RESET.startswith("\033[")

    def test_color_map_contains_all_log_levels(self):
        required_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

        for level in required_levels:
            assert level in COLOR_MAP

    def test_color_map_contains_name_and_location(self):
        assert "NAME" in COLOR_MAP
        assert "LOCATION" in COLOR_MAP

    def test_color_map_values_are_escape_sequences(self):
        for color in COLOR_MAP.values():
            assert color.startswith("\033[")


class TestLoggerIntegration:

    @pytest.fixture(autouse=True)
    def cleanup_loggers(self):
        yield
        logging_setup_module._loggers.clear()

    def test_logger_emits_records_to_handlers(self, caplog):
        with patch("etl.util.logging_setup.logging.FileHandler"):
            with caplog.at_level(logging.INFO):
                logger = get_logger("test.emit.unique")
                logger.info("test output message")

            assert any("test output message" in record.message for record in caplog.records)

    def test_logger_format_args_interpolated_in_output(self, caplog):
        with patch("etl.util.logging_setup.logging.FileHandler"):
            with caplog.at_level(logging.INFO):
                logger = get_logger("test.format.args.unique")
                logger.info("User %s logged in from %s", "test-user", "local")

            assert any("test-user" in record.message and "local" in record.message for record in caplog.records)

    def test_logger_exception_includes_traceback(self, caplog):
        with patch("etl.util.logging_setup.logging.FileHandler"):
            with caplog.at_level(logging.ERROR):
                logger = get_logger("test.exception.unique")

                try:
                    raise ValueError("test error")  # noqa: TRY301
                except ValueError:
                    logger.exception("An error occurred")

            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert len(error_records) == 1
            assert error_records[0].exc_info is not None
            assert error_records[0].exc_info[0] is ValueError
