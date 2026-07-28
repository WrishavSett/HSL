#!/usr/bin/python3
"""
errors.py
=========

Custom exception hierarchy for the HSL Invoice Extraction pipeline.

All pipeline exceptions inherit from :class:`HSLError`, which carries two
separate messages: a short, sanitised string safe to return to API callers
(``message``) and a full detail string intended for operator logs (``error``).
Subclasses map to distinct failure domains so catch sites can branch on error
category if needed.

Exception Hierarchy
-------------------
::

    HSLError
    ├── HSLConfigError    — config file validation failures
    ├── HSLPDFError       — PDF conversion failures
    ├── HSLGeminiError    — Gemini API and credential failures
    └── HSLStorageError   — temporary file I/O failures

Usage
-----
Raise at the failure site::

    from errors import HSLConfigError
    import logging

    raise HSLConfigError(
        message="Internal server error.",
        error=f"Config file {path!r} not found.",
        level=logging.CRITICAL,
    )

Catch by category in a handler::

    from errors import HSLError, HSLGeminiError

    try:
        result = client.extract_invoice_data(pdf_path)
    except HSLGeminiError as exc:
        return _error_response(exc.message, exc.error, 502)
    except HSLError as exc:
        return _error_response(exc.message, exc.error, 500)
"""

import logging


class HSLError(Exception):
    """
    Base pipeline exception carrying separate user-facing and operator-facing
    messages.

    All custom exceptions in the HSL pipeline inherit from this class.
    Catch :class:`HSLError` at the top level to handle any pipeline failure;
    catch a subclass to handle a specific failure domain.

    Parameters
    ----------
    message : str
        Short, sanitised string safe to return to API callers. Must not
        contain internal paths, credentials, or stack details.
    error : str
        Full detail string written to the log at the raise site. May contain
        paths, exception text, and any context useful for debugging.
    level : int, optional
        ``logging`` severity level at which this error was recorded (e.g.
        ``logging.ERROR``, ``logging.CRITICAL``). Defaults to
        ``logging.ERROR``. Stored for inspection by handlers that need to
        distinguish severity without re-examining the log.

    Examples
    --------
    ::

        raise HSLError(
            message="Internal server error.",
            error="Unexpected failure in resolve_paths: division by zero.",
        )
    """

    def __init__(self, message: str, error: str, level: int = logging.ERROR):
        super().__init__(message)
        self.message = message
        self.error   = error
        self.level   = level


class HSLConfigError(HSLError):
    """
    Raised for all configuration file validation failures.

    Covers every failure in :func:`helper.load_config`:

    - Config file not found on disk.
    - Config file contains invalid JSON.
    - Config file is missing one or more required top-level keys
      (``system_instruction``, ``prompt``, ``response_schema``,
      ``fields_of_interest``).
    - Any required key holds a value of the wrong type.
    - Any required string value is empty after stripping whitespace.
    - ``fields_of_interest`` contains a non-string or empty alias.
    - ``fields_of_interest`` contains a dot-path with an invalid segment.

    All config errors are raised at ``logging.CRITICAL`` because they are
    startup-blocking — the server cannot serve any requests until the config
    is valid.

    Examples
    --------
    ::

        raise HSLConfigError(
            message="Internal server error.",
            error=f"Config file {config_path!r} not found.",
            level=logging.CRITICAL,
        )
    """


class HSLPDFError(HSLError):
    """
    Raised for all PDF conversion failures.

    Covers every failure in :func:`helper.pdf_to_images`:

    - ``pdf2image`` package is not installed (``logging.CRITICAL``).
    - The PDF file does not exist on disk (``logging.ERROR``).
    - Poppler's ``pdfinfo`` utility is not installed or not on ``PATH``
      (``logging.ERROR``).
    - The page count cannot be read from the PDF —
      ``PDFPageCountError`` (``logging.ERROR``).
    - General conversion failure — any other exception from
      ``convert_from_path`` (``logging.ERROR``).
    - The PDF exceeds the configured ``max_pages`` limit
      (``logging.CRITICAL``).

    Examples
    --------
    ::

        raise HSLPDFError(
            message="PDF conversion failed for uploaded file.",
            error=f"PDF conversion failed for {pdf_path!r}: {exc}",
            level=logging.ERROR,
        )
    """


class HSLGeminiError(HSLError):
    """
    Raised for all Gemini API and credential failures.

    Covers every failure in :class:`gemini_client.GeminiClient`:

    - ``GEMINI_API_KEY`` environment variable is not set
      (``logging.CRITICAL``) — raised in ``__init__``.
    - ``GEMINI_MODEL_NAME`` environment variable is not set
      (``logging.CRITICAL``) — raised in ``__init__``.
    - The requested model name is not in the list of available Gemini models
      (``logging.CRITICAL``) — raised in ``_auth``.
    - The ``client.models.list()`` validation call fails for any reason
      (``logging.CRITICAL``) — raised in ``_auth``.
    - An image file passed to ``call_llm`` does not exist on disk
      (``logging.ERROR``) — raised in ``call_llm``.
    - An image file passed to ``call_llm`` cannot be read
      (``logging.ERROR``) — raised in ``call_llm``.
    - The ``generate_content`` API call fails for any reason — network error,
      quota exceeded, invalid schema, etc. (``logging.ERROR``) — raised in
      ``call_llm``.
    - ``response.parsed`` is ``None``, indicating no structured output was
      returned (``logging.ERROR``) — raised in ``extract_invoice_data``.

    Examples
    --------
    ::

        raise HSLGeminiError(
            message="Internal server error.",
            error=f"Gemini API call failed: {exc}",
            level=logging.ERROR,
        )
    """


class HSLStorageError(HSLError):
    """
    Raised for temporary file I/O failures.

    Covers every failure in :func:`api._save_upload`:

    - The temporary PDF file cannot be written due to an :class:`OSError`
      (e.g. permission denied, disk full) (``logging.ERROR``).

    Examples
    --------
    ::

        raise HSLStorageError(
            message="Internal server error.",
            error=f"Failed to write temporary PDF file at {temp_path}: {exc}",
            level=logging.ERROR,
        )
    """