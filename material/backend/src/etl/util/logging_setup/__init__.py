import logging
import sys
from logging import Logger

COLOR_RESET = "\033[0m"
COLOR_MAP = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[41m",
    "NAME": "\033[32m",
    "LOCATION": "\033[37m",
}

_loggers: dict[str, Logger] = {}

_log_level = logging.DEBUG


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds color to log output."""

    def formt(self, record: logging.LogRecord) -> str:
        """Format the log record with colors."""
        log_color = COLOR_MAP.get(record.levelname, COLOR_RESET)
        name_color = COLOR_MAP["NAME"]
        loc_color = COLOR_MAP["LOCATION"]

        location = f"{record.filename}:{record.lineno}"

        formatted = (
            f"{record.asctime} | "
            f"{name_color}{record.name}{COLOR_RESET} | "
            f"{loc_color}{location}{COLOR_RESET} | "
            f"{log_color}{record.levelname}{COLOR_RESET} | "
            f"{record.getMessage()}"
        )

        return formatted


def set_global_loglevel(level: str | int) -> None:
    """Set the log level for all loggers."""
    _log_level = level

    for logger in _loggers.values():
        logger.setLevel(_log_level)


def get_logger(name: str | None = None) -> Logger:
    """Get or create a logger with the given name."""
    name = name or __name__

    if name in _loggers:
        return _loggers[name]
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.hasHandlers():
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(
            ColoredFormatter(
                "[%(levelname)s] %(asctime)s - %(name)s: %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )

        logger.addHandler(ch)

        fh = logging.FileHandler("etl.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )

        logger.addHandler(fh)

        _loggers[name] = logger
    return logger
