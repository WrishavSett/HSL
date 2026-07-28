#!/usr/bin/python3
"""
helper.py
=========

Shared utilities for the HSL Invoice Extraction pipeline.

Provides
--------
load_config
    Load and validate the JSON extraction config (system instruction, prompt,
    response schema, and fields of interest).
pdf_to_images
    Convert each page of a PDF file to a JPEG or PNG image stored in a temp
    directory.
cleanup_temp_file
    Delete a single temporary file, silently ignoring missing-file errors.
cleanup_temp_files
    Delete a list of temporary files.
normalize_subtotal
    Strip non-numeric characters from a raw subtotal string, retaining at most
    one decimal point.
resolve_paths
    Walk a nested dict using dot-path expressions and collect values under
    caller-supplied aliases.

Dependencies
------------
- ``pdf2image`` — PDF-to-image conversion (requires Poppler on system PATH).

Install
-------
::

    pip install pdf2image
    # Ubuntu/Debian : sudo apt-get install poppler-utils
    # macOS         : brew install poppler
    # Windows       : download Poppler and add its bin/ folder to PATH
"""

import json
import logging
import os
import re

# ---------------------------------------------------------------------------
# Import logger and errors
# ---------------------------------------------------------------------------

from errors import HSLConfigError, HSLPDFError
from logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP_DIR     = os.getenv("TEMP_DIR") or os.path.join(_PROJECT_ROOT, "temp")

# ---------------------------------------------------------------------------
# Regular Expressions
# ---------------------------------------------------------------------------

_SEGMENT      = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?$")
_PATH_SEGMENT = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<idx>\d+)\])?$")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, str, dict, dict[str, str]]:
    """
    Load and validate the JSON extraction configuration file.

    Reads the file at ``config_path``, checks that all required top-level keys
    are present and hold values of the correct type, and validates every
    dot-path expression in ``fields_of_interest`` against the allowed segment
    pattern.

    Parameters
    ----------
    config_path : str
        Absolute or relative path to the JSON configuration file.

    Returns
    -------
    tuple[str, str, dict, dict[str, str]]
        A four-element tuple in the following order:

        - **prompt** (``str``) — The extraction prompt sent to the LLM.
        - **system_instruction** (``str``) — The system instruction for the LLM.
        - **response_schema** (``dict``) — JSON schema that constrains the LLM
          response.
        - **fields_of_interest** (``dict[str, str]``) — Mapping of output
          aliases to dot-path expressions (e.g. ``{"invoice_no":
          "invoice.number"}``).

    Raises
    ------
    HSLConfigError
        For any validation failure: missing file, invalid JSON, missing or
        wrong-typed keys, empty required values, or invalid dot-path segments.

    Example
    -------
    ::

        prompt, system_instruction, schema, fields = load_config(
            "/app/configs/extraction.json"
        )
    """
    if not os.path.exists(config_path):
        log_msg = (
            f"Config file not found: {config_path!r}.\n"
            "Ensure the path is correct and the file exists."
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file not found.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        log_msg = (
            f"Config file {config_path!r} contains invalid JSON.\n"
            f"Parser error: {exc}"
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file contains invalid JSON.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    required_keys = ("system_instruction", "prompt", "response_schema", "fields_of_interest")
    missing = [k for k in required_keys if k not in config]
    if missing:
        log_msg = (
            f"Config file {config_path!r} is missing required key(s): {missing}\n"
            'Expected: { "system_instruction": "...", "prompt": "...", '
            '"response_schema": { ... }, "fields_of_interest": { ... } }'
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file is missing required keys.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not isinstance(config["system_instruction"], str):
        log_msg = (
            f'"system_instruction" in {config_path!r} must be a string, '
            f'got {type(config["system_instruction"]).__name__}.'
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'system_instruction' must be a string.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not isinstance(config["prompt"], str):
        log_msg = (
            f'"prompt" in {config_path!r} must be a string, '
            f'got {type(config["prompt"]).__name__}.'
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'prompt' must be a string.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not isinstance(config["response_schema"], dict):
        log_msg = (
            f'"response_schema" in {config_path!r} must be an object/dict, '
            f'got {type(config["response_schema"]).__name__}.'
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'response_schema' must be an object/dict.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not isinstance(config["fields_of_interest"], dict):
        log_msg = (
            f'"fields_of_interest" in {config_path!r} must be an object/dict, '
            f'got {type(config["fields_of_interest"]).__name__}.'
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'fields_of_interest' must be an object/dict.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not config["system_instruction"].strip():
        log_msg = (
            f'"system_instruction" in {config_path!r} is empty. '
            "Provide non-empty extraction rules."
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'system_instruction' is empty.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not config["prompt"].strip():
        log_msg = (
            f'"prompt" in {config_path!r} is empty. '
            "Provide a non-empty extraction prompt."
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'prompt' is empty.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not config["response_schema"]:
        log_msg = (
            f'"response_schema" in {config_path!r} is an empty object. '
            "Provide a valid JSON schema."
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'response_schema' is an empty object.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not config["fields_of_interest"]:
        log_msg = (
            f'"fields_of_interest" in {config_path!r} is an empty object. '
            "Provide at least one alias to dot-path entry."
        )
        log.critical(log_msg)
        raise HSLConfigError(
            message="Config file - 'fields_of_interest' is an empty object.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    for alias, path in config["fields_of_interest"].items():
        if not isinstance(alias, str) or not alias.strip():
            log_msg = (
                f'"fields_of_interest" in {config_path!r} contains a non-string or empty alias.'
            )
            log.critical(log_msg)
            raise HSLConfigError(
                message="Config file - 'fields_of_interest' contains invalid alias.",
                error=log_msg,
                level=logging.CRITICAL,
            )

        if not isinstance(path, str) or not path.strip():
            log_msg = (
                f'"fields_of_interest[{alias!r}]" in {config_path!r} must be a non-empty dot-path string.'
            )
            log.critical(log_msg)
            raise HSLConfigError(
                message="Config file - 'fields_of_interest' contains invalid path.",
                error=log_msg,
                level=logging.CRITICAL,
            )

        segments = path.split(".")
        for seg in segments:
            if not _SEGMENT.match(seg):
                log_msg = (
                    f'"fields_of_interest[{alias!r}]" in {config_path!r} contains an invalid '
                    f'path segment {seg!r}. '
                    "Segments must be identifiers, optionally followed by an array index like [0]."
                )
                log.critical(log_msg)
                raise HSLConfigError(
                    message="Config file - 'fields_of_interest' contains invalid path segment.",
                    error=log_msg,
                    level=logging.CRITICAL,
                )

    return (
        config["prompt"],
        config["system_instruction"],
        config["response_schema"],
        config["fields_of_interest"],
    )

# ---------------------------------------------------------------------------
# PDF to image
# ---------------------------------------------------------------------------

def pdf_to_images(
    pdf_path: str,
    temp_dir: str = _TEMP_DIR,
    dpi: int = 200,
    fmt: str = "jpeg",
    max_pages: int = 30,
) -> list[str]:
    """
    Convert each page of a PDF file to an image and save the results to disk.

    Uses ``pdf2image.convert_from_path`` (which requires Poppler on the system
    PATH) to rasterise every page at the requested DPI.  Output images are
    written to ``temp_dir`` and named ``<pdf_stem>_p<page_number>.<ext>``.

    Parameters
    ----------
    pdf_path : str
        Path to the source PDF file.
    temp_dir : str, optional
        Directory in which to save the generated image files.  Created
        automatically if it does not exist.  Defaults to the value of the
        ``TEMP_DIR`` environment variable, or ``<project_root>/temp``.
    dpi : int, optional
        Rasterisation resolution in dots per inch.  Higher values improve OCR
        accuracy at the cost of larger files and slower processing.
        Defaults to ``200``.
    fmt : str, optional
        Output image format.  Accepts ``"jpeg"`` / ``"jpg"`` (default) or
        ``"png"``.
    max_pages : int, optional
        Maximum number of pages permitted in the PDF.  Raises
        :class:`HSLPDFError` if the document exceeds this limit.
        Defaults to ``30``.

    Returns
    -------
    list[str]
        Ordered list of absolute paths to the generated image files, one entry
        per PDF page.

    Raises
    ------
    HSLPDFError
        If ``pdf2image`` is not installed, ``pdf_path`` does not exist,
        Poppler is missing, the page count cannot be determined, the
        conversion fails, or the PDF exceeds ``max_pages``.

    Example
    -------
    ::

        image_paths = pdf_to_images("/invoices/invoice_001.pdf", dpi=300)
        # ["/tmp/hsl/invoice_001_p1.jpg", "/tmp/hsl/invoice_001_p2.jpg"]
    """
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
    except ImportError:
        log_msg = (
            "pdf2image is required for PDF support.\n"
            "Install it with: pip install pdf2image\n"
            "You also need Poppler on your system PATH:\n"
            "  Ubuntu/Debian : sudo apt-get install poppler-utils\n"
            "  macOS         : brew install poppler\n"
            "  Windows       : download poppler and add its bin/ to PATH"
        )
        log.critical(log_msg)
        raise HSLPDFError(
            message="Internal server error.",
            error=log_msg,
            level=logging.CRITICAL,
        )

    if not os.path.exists(pdf_path):
        log_msg = (
            f"PDF file not found: {pdf_path!r}.\n"
            "Ensure the path is correct and the file exists."
        )
        log.error(log_msg)
        raise HSLPDFError(
            message="Internal server error.",
            error=log_msg,
            level=logging.ERROR,
        )

    os.makedirs(temp_dir, exist_ok=True)
    extension = "jpg" if fmt.lower() in ("jpeg", "jpg") else fmt.lower()

    try:
        pages = convert_from_path(pdf_path, dpi=dpi, fmt=fmt)
        log.debug(
            f"Converted PDF {pdf_path!r} to {len(pages)} image(s) "
            f"at {dpi} DPI in {fmt.upper()} format."
        )
    except PDFInfoNotInstalledError:
        log_msg = (
            "Poppler's pdfinfo utility was not found.\n"
            "Install Poppler and make sure its executables are on your PATH."
        )
        log.error(log_msg)
        raise HSLPDFError(
            message="Internal server error.",
            error=log_msg,
            level=logging.ERROR,
        )
    except PDFPageCountError as exc:
        log_msg = f"Could not read page count from {pdf_path!r}: {exc}"
        log.error(log_msg)
        raise HSLPDFError(
            message="Could not read page count from uploaded file.",
            error=log_msg,
            level=logging.ERROR,
        )
    except Exception as exc:
        log_msg = f"PDF conversion failed for {pdf_path!r}: {exc}"
        log.error(log_msg)
        raise HSLPDFError(
            message="PDF conversion failed for uploaded file.",
            error=log_msg,
            level=logging.ERROR,
        )

    if len(pages) > max_pages:
        log_msg = (
            f"PDF has {len(pages)} pages, which exceeds the limit of {max_pages}.\n"
            "Split the document or raise max_pages."
        )
        log.critical(log_msg)
        raise HSLPDFError(
            message=(
                f"PDF has {len(pages)} pages, which exceeds the limit of {max_pages}. "
                "Split the document upload."
            ),
            error=log_msg,
            level=logging.CRITICAL,
        )

    pdf_stem = os.path.splitext(os.path.basename(pdf_path))[0]
    page_fmt = "JPEG" if extension == "jpg" else fmt.upper()
    saved: list[str] = []
    for i, page in enumerate(pages, start=1):
        out_path = os.path.join(temp_dir, f"{pdf_stem}_p{i}.{extension}")
        page.save(out_path, page_fmt)
        saved.append(out_path)
    return saved

# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

def cleanup_temp_file(path: str) -> None:
    """
    Delete a single temporary file from disk.

    Silently ignores the case where the file has already been removed (e.g. by
    a previous cleanup call or an OS-level action).  All other ``OSError``
    subclasses are allowed to propagate.

    Parameters
    ----------
    path : str
        Absolute or relative path to the file to delete.

    Example
    -------
    ::

        cleanup_temp_file("/tmp/hsl/abc123_upload.pdf")
    """
    try:
        os.remove(path)
        log.debug(f"Cleaned up temporary file: {path}")
    except FileNotFoundError:
        pass

def cleanup_temp_files(paths: list[str]) -> None:
    """
    Delete a list of temporary files from disk.

    Delegates each deletion to :func:`cleanup_temp_file`, so missing files are
    silently skipped.

    Parameters
    ----------
    paths : list[str]
        List of absolute or relative file paths to delete.

    Example
    -------
    ::

        cleanup_temp_files([
            "/tmp/hsl/invoice_001_p1.jpg",
            "/tmp/hsl/invoice_001_p2.jpg",
        ])
    """
    for path in paths:
        cleanup_temp_file(path)

# ---------------------------------------------------------------------------
# Subtotal normalisation
# ---------------------------------------------------------------------------

def normalize_subtotal(value: str) -> str:
    """
    Strip non-numeric characters from a raw subtotal string.

    Locates the span between the first and last digit in ``value``, removes
    everything that is not a digit or a decimal point from that span, and
    returns the result.  If the cleaned span contains more than one decimal
    point the original ``value`` is returned unchanged, since the input is
    ambiguous.

    Parameters
    ----------
    value : str
        Raw subtotal string as returned by the LLM (e.g. ``"$1,234.56"``
        or ``"1.234,56 USD"``).

    Returns
    -------
    str
        Cleaned numeric string (e.g. ``"1234.56"``), or the original
        ``value`` if no digits are found or if multiple decimal points
        remain after cleaning.

    Examples
    --------
    ::

        normalize_subtotal("$1,234.56")   # "1234.56"
        normalize_subtotal("1.234,56")    # "1.234,56"  (ambiguous — returned as-is)
        normalize_subtotal("no digits")   # "no digits" (no digits found)
    """
    first = re.search(r'\d', value)
    if not first:
        return value

    last = re.search(r'\d(?=[^\d]*$)', value)
    span = value[first.start(): last.end()]

    result = re.sub(r'[^\d.]', '', span)
    if result.count('.') > 1:
        log.debug(
            f"normalize_subtotal: multiple decimal points found in {result!r},\n"
            f"returning original value {value!r}"
        )
        return value

    return result

# ---------------------------------------------------------------------------
# Dot-path field resolution
# ---------------------------------------------------------------------------

def resolve_paths(
    data: dict,
    fields_of_interest: dict[str, str],
) -> dict[str, object]:
    """
    Extract values from a nested dict using dot-path expressions.

    For each ``alias → path`` pair in ``fields_of_interest``, the function
    traverses ``data`` one segment at a time.  A segment may be a plain dict
    key (``"invoice"``) or a key followed by an array index (``"items[0]"``).
    If any segment is missing or the index is out of bounds, the alias is
    mapped to ``None`` in the result.

    For the ``"subtotal"`` alias, the resolved string value is passed through
    :func:`normalize_subtotal` before being stored.

    Parameters
    ----------
    data : dict
        Nested dictionary returned by the Gemini LLM (i.e. ``response.parsed``).
    fields_of_interest : dict[str, str]
        Mapping of output alias to dot-path expression, as loaded by
        :func:`load_config`.  Example::

            {
                "company_name": "vendor.name",
                "invoice_no":   "invoice.number",
                "po_no":        "purchase_order.number",
                "subtotal":     "totals.subtotal",
            }

    Returns
    -------
    dict[str, object]
        Flat dictionary mapping each alias to its resolved value, or ``None``
        if the path could not be followed.

    Examples
    --------
    ::

        data = {
            "vendor": {"name": "Acme Corp"},
            "totals": {"subtotal": "$1,200.00"},
        }
        fields = {"company_name": "vendor.name", "subtotal": "totals.subtotal"}
        resolve_paths(data, fields)
        # {"company_name": "Acme Corp", "subtotal": "1200.00"}
    """
    result: dict[str, object] = {}

    for alias, path in fields_of_interest.items():
        node: object = data

        for segment in path.split("."):
            match = _PATH_SEGMENT.match(segment)
            if not match:
                node = None
                break

            key = match.group("key")
            idx = match.group("idx")

            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]

            if idx is not None:
                i = int(idx)
                if not isinstance(node, list) or i >= len(node):
                    node = None
                    break
                node = node[i]

        if alias == "subtotal" and isinstance(node, str):
            node = normalize_subtotal(node)
        result[alias] = node

    return result