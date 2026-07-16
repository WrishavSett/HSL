#!/usr/bin/python3
"""
logger.py — Centralised logging for the HSL Invoice Extraction pipeline.

Provides a single configured logger ("hsl") that writes to both the console
and a rotating log file. Import get_logger() in any module; all calls share
the same handler set, so there is no duplicate output.

Usage:
    from logger import get_logger
    log = get_logger(__name__)

    log.info("Starting extraction for %s", pdf_path)
    log.warning("Gemini returned empty parsed output.")
    log.error("PDF conversion failed: %s", exc)
    log.exception("Unhandled error in extract()")   # includes traceback
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOGGER_NAME   = "hsl"
_LOG_DIR       = os.getenv("LOG_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
)
_LOG_FILE      = os.path.join(_LOG_DIR, "hsl.log")
_LOG_LEVEL     = os.getenv("LOG_LEVEL", "INFO").upper()
_MAX_BYTES     = 5 * 1024 * 1024   # 5 MB per file
_BACKUP_COUNT  = 5                  # keep hsl.log … hsl.log.5

_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ---------------------------------------------------------------------------
# Internal setup (runs once on first import)
# ---------------------------------------------------------------------------

def _build_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)

    # Guard: if handlers are already attached a second import won't add duplicates.
    if logger.handlers:
        return logger

    level = getattr(logging, _LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

    # --- Rotating file handler ---
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not create log file at %r: %s — logging to console only.", _LOG_FILE, exc)

    # Prevent log records from propagating to the root logger.
    logger.propagate = False

    return logger


_logger = _build_logger()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str = "") -> logging.Logger:
    """
    Return a child of the root "hsl" logger namespaced by *name*.

    All child loggers share the handlers configured on the "hsl" logger, so
    output is unified in both the console and the rotating log file.

    Args:
        name (str): Typically __name__ of the calling module.
                    Pass an empty string to get the root "hsl" logger directly.

    Returns:
        logging.Logger: A logger named "hsl.<name>" (or "hsl" if name is empty).

    Example:
        log = get_logger(__name__)
        log.info("PDF saved to %s", path)
    """
    if not name or name == _LOGGER_NAME:
        return _logger
    return _logger.getChild(name)