#!/usr/bin/python3
"""
helper.py — Shared utilities for the HSL Invoice Extraction pipeline.

Provides:
  - Config loading and validation  (load_config)
  - PDF → image conversion         (pdf_to_image)
  - Temp file cleanup              (cleanup_temp_file)
  - Dot-path field resolution      (resolve_paths)
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMP_DIR     = os.getenv("TEMP_DIR") or os.path.join(_PROJECT_ROOT, "temp")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, dict, dict[str, str]]:
    """
    Load and validate a document config .json file.

    The file must be a JSON object with exactly three top-level keys:

        - ``"prompt"``             (str)          : extraction instructions for the model.
        - ``"response_schema"``    (dict)         : JSON schema that constrains model output.
        - ``"fields_of_interest"`` (dict[str,str]): aliased dot-path map of fields to return.

    Args:
        config_path (str): Absolute or relative path to the .json config file.

    Returns:
        tuple[str, dict, dict[str, str]]: ``(prompt, response_schema, fields_of_interest)``

    Raises:
        FileNotFoundError : If *config_path* does not exist on disk.
        ValueError        : If the file is invalid JSON, is missing required
                            keys, has wrong types, or contains empty/invalid values.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found: {config_path!r}\n"
            "Ensure the path is correct and the file exists."
        )

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Config file {config_path!r} contains invalid JSON.\n"
            f"Parser error: {exc}"
        )

    missing = [k for k in ("prompt", "response_schema", "fields_of_interest") if k not in config]
    if missing:
        raise ValueError(
            f"Config file {config_path!r} is missing required key(s): {missing}\n"
            'Expected: { "prompt": "...", "response_schema": { ... }, "fields_of_interest": { ... } }'
        )

    if not isinstance(config["prompt"], str):
        raise ValueError(
            f'"prompt" in {config_path!r} must be a string, '
            f'got {type(config["prompt"]).__name__}.'
        )
    if not isinstance(config["response_schema"], dict):
        raise ValueError(
            f'"response_schema" in {config_path!r} must be an object/dict, '
            f'got {type(config["response_schema"]).__name__}.'
        )
    if not isinstance(config["fields_of_interest"], dict):
        raise ValueError(
            f'"fields_of_interest" in {config_path!r} must be an object/dict, '
            f'got {type(config["fields_of_interest"]).__name__}.'
        )
    if not config["prompt"].strip():
        raise ValueError(
            f'"prompt" in {config_path!r} is empty. Provide a non-empty extraction prompt.'
        )
    if not config["response_schema"]:
        raise ValueError(
            f'"response_schema" in {config_path!r} is an empty object. '
            "Provide a valid JSON schema."
        )
    if not config["fields_of_interest"]:
        raise ValueError(
            f'"fields_of_interest" in {config_path!r} is an empty object. '
            "Provide at least one alias → dot-path entry."
        )

    # Validate that every entry is a non-empty string alias → non-empty string path,
    # and that each path segment is a valid identifier (with optional array index).
    _SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?$")
    for alias, path in config["fields_of_interest"].items():
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(
                f'"fields_of_interest" in {config_path!r} contains a non-string or empty alias.'
            )
        if not isinstance(path, str) or not path.strip():
            raise ValueError(
                f'"fields_of_interest[{alias!r}]" in {config_path!r} must be a non-empty dot-path string.'
            )
        segments = path.split(".")
        for seg in segments:
            if not _SEGMENT.match(seg):
                raise ValueError(
                    f'"fields_of_interest[{alias!r}]" in {config_path!r} contains an invalid '
                    f'path segment {seg!r}. '
                    "Segments must be identifiers, optionally followed by an array index like [0]."
                )

    return config["prompt"], config["response_schema"], config["fields_of_interest"]

# ---------------------------------------------------------------------------
# PDF → image
# ---------------------------------------------------------------------------

def pdf_to_image(
    pdf_path: str,
    temp_dir: str = _TEMP_DIR,
    dpi: int = 400,
    fmt: str = "jpeg",
) -> str:
    """
    Rasterise the first page of a PDF into an image file stored in *temp_dir*.

    Uses ``pdf2image`` (which wraps Poppler's ``pdftoppm``).
    Install dependencies with::

        pip install pdf2image
        # Ubuntu/Debian : sudo apt-get install poppler-utils
        # macOS         : brew install poppler
        # Windows       : download poppler and add its bin/ to PATH

    Args:
        pdf_path (str):  Absolute or relative path to the source PDF file.
        temp_dir (str):  Directory to write the converted image into.
                         Created automatically if it does not exist.
                         Defaults to ``HSL/temp/``.
        dpi (int):       Rendering resolution in dots per inch (default 400).
                         Higher values improve OCR accuracy at the cost of
                         larger files and slower processing.
        fmt (str):       Output image format — ``"jpeg"`` (default) or ``"png"``.

    Returns:
        str: Absolute path to the generated image file
             (e.g. ``".../temp/tax_invoice.jpg"``).

    Raises:
        ImportError       : If ``pdf2image`` is not installed.
        FileNotFoundError : If *pdf_path* does not exist.
        RuntimeError      : If Poppler is absent from PATH or conversion fails.
    """
    try:
        from pdf2image import convert_from_path
        from pdf2image.exceptions import PDFInfoNotInstalledError, PDFPageCountError
    except ImportError:
        raise ImportError(
            "pdf2image is required for PDF support.\n"
            "Install it with: pip install pdf2image\n"
            "You also need Poppler on your system PATH:\n"
            "  Ubuntu/Debian : sudo apt-get install poppler-utils\n"
            "  macOS         : brew install poppler\n"
            "  Windows       : download poppler and add its bin/ to PATH"
        )

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF file not found: {pdf_path!r}\n"
            "Ensure the path is correct and the file exists."
        )

    os.makedirs(temp_dir, exist_ok=True)
    extension = "jpg" if fmt.lower() in ("jpeg", "jpg") else fmt.lower()

    try:
        pages = convert_from_path(pdf_path, dpi=dpi, fmt=fmt)
    except PDFInfoNotInstalledError:
        raise RuntimeError(
            "Poppler's pdfinfo utility was not found.\n"
            "Install Poppler and make sure its executables are on your PATH."
        )
    except PDFPageCountError as exc:
        raise RuntimeError(f"Could not read page count from {pdf_path!r}: {exc}")
    except Exception as exc:
        raise RuntimeError(f"PDF conversion failed for {pdf_path!r}: {exc}")

    pdf_stem  = os.path.splitext(os.path.basename(pdf_path))[0]
    full_path = os.path.join(temp_dir, f"{pdf_stem}.{extension}")
    page_fmt  = "JPEG" if extension == "jpg" else fmt.upper()
    pages[0].save(full_path, page_fmt)

    return full_path

# ---------------------------------------------------------------------------
# Temp file cleanup
# ---------------------------------------------------------------------------

def cleanup_temp_file(path: str) -> None:
    """
    Delete a temporary file, silently ignoring missing-file errors.

    Args:
        path (str): File path to remove.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

# ---------------------------------------------------------------------------
# Dot-path field resolution
# ---------------------------------------------------------------------------

# Matches a bare key ("letter_head") or a key with an array index ("line_items[2]").
_PATH_SEGMENT = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<idx>\d+)\])?$")


def resolve_paths(
    data: dict,
    fields_of_interest: dict[str, str],
) -> dict[str, object]:
    """
    Resolve a set of dot-path expressions against *data* and return a flat
    mapping of alias → value.

    Each path in *fields_of_interest* is a dot-separated sequence of dict keys
    with optional array indices, e.g.::

        "letter_head.company_name"       →  data["letter_head"]["company_name"]
        "line_items[0].hsn"              →  data["line_items"][0]["hsn"]
        "tax_breakup.total_amount_before_tax"

    If any segment along a path is missing, out of range, or the wrong type,
    the alias resolves to ``None`` rather than raising — this mirrors the
    original behaviour for absent fields.

    Args:
        data (dict):                     Parsed Gemini response.
        fields_of_interest (dict[str,str]): Mapping of output alias → dot-path.

    Returns:
        dict[str, object]: Flat mapping of alias → resolved value (or ``None``).

    Example:
        >>> resolve_paths(parsed, {
        ...     "company_name": "letter_head.company_name",
        ...     "invoice_no":   "invoice_details.invoice_no",
        ... })
        {"company_name": "DCG Data-Core Systems ...", "invoice_no": "DC/25-26/03/0020"}
    """
    result: dict[str, object] = {}

    for alias, path in fields_of_interest.items():
        node: object = data

        for segment in path.split("."):
            match = _PATH_SEGMENT.match(segment)
            if not match:
                # Malformed segment — path validation in load_config should catch
                # this at startup, but guard here defensively.
                node = None
                break

            key = match.group("key")
            idx = match.group("idx")

            # Descend into the dict key.
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]

            # If an array index was specified, descend into the list.
            if idx is not None:
                i = int(idx)
                if not isinstance(node, list) or i >= len(node):
                    node = None
                    break
                node = node[i]

        result[alias] = node

    return result