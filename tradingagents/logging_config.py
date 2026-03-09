"""
logging_config.py - Centralized logging configuration for TradingAgents.

Sets up a RotatingFileHandler that caps log files at 10 MB with 5 backups,
writing to logs/tradingagents.log.  Call setup_logging() once at server
startup before importing any other project modules.
"""

import logging
import logging.handlers
import os
from pathlib import Path


_LOG_DIR = "logs"
_LOG_FILE = "tradingagents.log"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with a RotatingFileHandler and a StreamHandler.

    Idempotent — calling it more than once is safe.

    Args:
        level: Minimum log level for the root logger (default: INFO).
    """
    global _configured
    if _configured:
        return
    _configured = True

    Path(_LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(_LOG_DIR, _LOG_FILE)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    rotating_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    rotating_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(rotating_handler)
    root.addHandler(stream_handler)

    # Silence noisy third-party loggers
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("dash").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Args:
        name: Logger name (typically __name__ of the calling module).

    Returns:
        logging.Logger instance.
    """
    return logging.getLogger(name)
