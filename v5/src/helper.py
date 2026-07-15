#!/usr/bin/python3
"""
helper.py — Shared utilities for the HSL Invoice Extraction pipeline.

Provides:
  - Config loading and validation  (load_config) — now includes system_instruction
  - PDF → image conversion         (pdf_to_images)
  - Temp file cleanup              (cleanup_temp_file, cleanup_temp_files)
  - Subtotal normalisation         (normalize_subtotal)
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
# Regular Expressions
# ---------------------------------------------------------------------------

_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])?$")
_PATH_SEGMENT = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<idx>\d+)\])?$")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> tuple[str, str, dict, dict[str, str]]:
    """
    Load and validate the extraction config .json file.

    The file must be a JSON object with exactly four top-level keys:

        - ``"system_instruction"`` (str)          : persona + field-extraction rules for the model.
        - ``"prompt"``             (str)          : per-call trigger instruction for the model.
        - ``"response_schema"``    (dict)         : JSON schema that constrains model output.
        - ``"fields_of_interest"`` (dict[str,str]): aliased dot-path map of fields to return.

    Args:
        config_path (str): Absolute or relative path to the .json config file.

    Returns:
        tuple[str, str, dict, dict[str, str]]:
            ``(prompt, system_instruction, response_schema, fields_of_interest)``

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

    required_keys = ("system_instruction", "prompt", "response_schema", "fields_of_interest")
    missing = [k for k in required_keys if k not in config]
    if missing:
        raise ValueError(
            f"Config file {config_path!r} is missing required key(s): {missing}\n"
            'Expected: { "system_instruction": "...", "prompt": "...", '
            '"response_schema": { ... }, "fields_of_interest": { ... } }'
        )

    if not isinstance(config["system_instruction"], str):
        raise ValueError(
            f'"system_instruction" in {config_path!r} must be a string, '
            f'got {type(config["system_instruction"]).__name__}.'
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
    if not config["system_instruction"].strip():
        raise ValueError(
            f'"system_instruction" in {config_path!r} is empty. '
            "Provide non-empty extraction rules."
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

    return (
        config["prompt"],
        config["system_instruction"],
        config["response_schema"],
        config["fields_of_interest"],
    )

# ---------------------------------------------------------------------------
# PDF → image
# ---------------------------------------------------------------------------

def pdf_to_images(
    pdf_path: str,
    temp_dir: str = _TEMP_DIR,
    dpi: int = 200,
    fmt: str = "jpeg",
    max_pages: int = 30,
) -> list[str]:
    """
    Rasterise all pages of a PDF into image files stored in *temp_dir*.

    Uses ``pdf2image`` (which wraps Poppler's ``pdftoppm``).
    Install dependencies with::

        pip install pdf2image
        # Ubuntu/Debian : sudo apt-get install poppler-utils
        # macOS         : brew install poppler
        # Windows       : download poppler and add its bin/ to PATH

    Args:
        pdf_path (str):   Absolute or relative path to the source PDF file.
        temp_dir (str):   Directory to write the converted images into.
                          Created automatically if it does not exist.
                          Defaults to ``HSL/temp/``.
        dpi (int):        Rendering resolution in dots per inch (default 200).
                          Higher values improve OCR accuracy at the cost of
                          larger files and slower processing.
        fmt (str):        Output image format — ``"jpeg"`` (default) or ``"png"``.
        max_pages (int):  Maximum number of pages permitted. Raises ``ValueError``
                          if the PDF exceeds this limit (default 30).

    Returns:
        list[str]: Absolute paths to the generated image files, one per page,
                   in page order (e.g. ``[".../temp/invoice_p1.jpg", ".../temp/invoice_p2.jpg"]``).

    Raises:
        ImportError       : If ``pdf2image`` is not installed.
        FileNotFoundError : If *pdf_path* does not exist.
        ValueError        : If the PDF has more pages than *max_pages*.
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

    if len(pages) > max_pages:
        raise ValueError(
            f"PDF has {len(pages)} pages, which exceeds the limit of {max_pages}. "
            "Split the document or raise max_pages."
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
    Delete a temporary file, silently ignoring missing-file errors.

    Args:
        path (str): File path to remove.
    """
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

def cleanup_temp_files(paths: list[str]) -> None:
    """
    Delete a list of temporary files, silently ignoring missing-file errors.

    Args:
        paths (list[str]): File paths to remove.
    """
    for path in paths:
        cleanup_temp_file(path)

# ---------------------------------------------------------------------------
# Subtotal normalisation
# ---------------------------------------------------------------------------

def normalize_subtotal(value: str) -> str:
    """
    Extract a plain numeric string from a subtotal value returned by Gemini.

    Algorithm:
      1. Find the first and last digit in the string and discard everything
         outside that span (e.g. leading ``"Rs. "`` and trailing ``"/-"``).
      2. From the remaining span, keep only digits and at most one decimal
         point; discard everything else (currency symbols, commas, spaces).
      3. If no digit exists anywhere in the string, return the value unchanged.
      4. If more than one decimal point is found after cleaning, return the
         original value unchanged.

    Args:
        value (str): Raw subtotal string from the Gemini response.

    Returns:
        str: Plain numeric string (e.g. ``"491716.95"`` or ``"100000"``),
             or the original *value* if no digit could be found or if more
             than one decimal point is present after cleaning.

    Examples:
        >>> normalize_subtotal("4,91,716.95")
        '491716.95'
        >>> normalize_subtotal("₹ 4,91,716.95/-")
        '491716.95'
        >>> normalize_subtotal("Rs. 4,91,716.95")
        '491716.95'
        >>> normalize_subtotal("1,00,000")
        '100000'
        >>> normalize_subtotal("₹ 500")
        '500'
        >>> normalize_subtotal("4.91.716.95")
        '4.91.716.95'
        >>> normalize_subtotal("N/A")
        'N/A'
    """
    first = re.search(r'\d', value)
    if not first:
        return value

    last = re.search(r'\d(?=[^\d]*$)', value)
    span = value[first.start(): last.end()]

    result = re.sub(r'[^\d.]', '', span)
    if result.count('.') > 1:
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

        if alias == "subtotal" and isinstance(node, str):
            node = normalize_subtotal(node)
        result[alias] = node

    return result