#!/usr/bin/python3
"""
errors.py — Centralised error taxonomy for the HSL Invoice Extraction pipeline.

Every error in the pipeline is represented by an HSLError subclass carrying:
    - code        (int)  : numeric code grouping errors by domain
    - description (str)  : human-readable explanation, safe to surface to callers
    - http_status (int)  : the most semantically correct HTTP status for this error
    - detail      (str)  : optional low-level detail added at raise time (not always set)

Code ranges
-----------
    1xx  Configuration errors   — malformed or missing config / environment
    2xx  File & I/O errors      — missing files, unreadable content, filesystem failures
    3xx  PDF processing errors  — pdf2image / Poppler failures, page-count limits
    4xx  Gemini / LLM errors    — auth, quota, network, bad model response
    5xx  API / request errors   — invalid uploads, unsupported media, empty bodies

Usage
-----
    from errors import GeminiAuthError, PDFConversionError

    raise GeminiAuthError()
    raise PDFConversionError(detail="pdftoppm exited with code 1")

Catching in api.py
------------------
    except HSLError as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.to_dict())
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class HSLError(Exception):
    """Base class for all pipeline errors."""

    code:        int = 0
    description: str = "An unexpected error occurred."
    http_status: int = 500

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(self.description)

    def to_dict(self) -> dict:
        """
        Serialisable representation suitable for JSONResponse / HTTPException detail.

        Returns:
            dict: {code, description, detail}  — detail is omitted when empty.
        """
        payload: dict = {
            "code":        self.code,
            "description": self.description,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code}, "
            f"http_status={self.http_status}, "
            f"description={self.description!r}"
            + (f", detail={self.detail!r}" if self.detail else "")
            + ")"
        )


# ---------------------------------------------------------------------------
# 1xx — Configuration errors
# ---------------------------------------------------------------------------

class ConfigNotFoundError(HSLError):
    """Config file does not exist at the given path."""
    code        = 101
    description = "Configuration file not found."
    http_status = 500

class ConfigInvalidJSONError(HSLError):
    """Config file exists but contains invalid JSON."""
    code        = 102
    description = "Configuration file contains invalid JSON."
    http_status = 500

class ConfigMissingKeyError(HSLError):
    """One or more required top-level keys are absent from the config."""
    code        = 103
    description = "Configuration file is missing required key(s)."
    http_status = 500

class ConfigTypeError(HSLError):
    """A config value has the wrong type (e.g. prompt is not a string)."""
    code        = 104
    description = "Configuration file contains a value of an unexpected type."
    http_status = 500

class ConfigEmptyValueError(HSLError):
    """A required config value is present but empty."""
    code        = 105
    description = "Configuration file contains an empty required value."
    http_status = 500

class ConfigInvalidPathError(HSLError):
    """A dot-path in fields_of_interest contains an invalid segment."""
    code        = 106
    description = "Configuration file contains an invalid field path."
    http_status = 500

class MissingAPIKeyError(HSLError):
    """GEMINI_API_KEY environment variable is not set."""
    code        = 107
    description = "Gemini API key is not configured. Set the GEMINI_API_KEY environment variable."
    http_status = 500

class MissingModelNameError(HSLError):
    """GEMINI_MODEL_NAME environment variable is not set."""
    code        = 108
    description = "Gemini model name is not configured. Set the GEMINI_MODEL_NAME environment variable."
    http_status = 500


# ---------------------------------------------------------------------------
# 2xx — File & I/O errors
# ---------------------------------------------------------------------------

class PDFNotFoundError(HSLError):
    """The source PDF file does not exist on disk."""
    code        = 201
    description = "PDF file not found."
    http_status = 404

class ImageNotFoundError(HSLError):
    """A converted page image is missing when the LLM call is attempted."""
    code        = 202
    description = "Converted page image not found."
    http_status = 500

class ImageReadError(HSLError):
    """A converted page image exists but cannot be read (permissions, corruption)."""
    code        = 203
    description = "Could not read converted page image."
    http_status = 500

class TempFileWriteError(HSLError):
    """The pipeline could not write a temporary file (disk full, permissions)."""
    code        = 204
    description = "Could not write temporary file."
    http_status = 500

class LogDirectoryError(HSLError):
    """The log directory could not be created or written to."""
    code        = 205
    description = "Could not initialise log directory."
    http_status = 500


# ---------------------------------------------------------------------------
# 3xx — PDF processing errors
# ---------------------------------------------------------------------------

class PDFConversionError(HSLError):
    """pdf2image / Poppler failed to rasterise the PDF."""
    code        = 301
    description = "PDF conversion failed."
    http_status = 422

class PDFPageLimitExceededError(HSLError):
    """The PDF has more pages than the configured max_pages limit."""
    code        = 302
    description = "PDF exceeds the maximum permitted page count."
    http_status = 422

class PopperNotInstalledError(HSLError):
    """Poppler utilities are not present on the system PATH."""
    code        = 303
    description = "Poppler is not installed or not on PATH. PDF conversion is unavailable."
    http_status = 500

class PDF2ImageNotInstalledError(HSLError):
    """The pdf2image Python package is not installed."""
    code        = 304
    description = "pdf2image is not installed. Run: pip install pdf2image"
    http_status = 500


# ---------------------------------------------------------------------------
# 4xx — Gemini / LLM errors
# ---------------------------------------------------------------------------

class GeminiAuthError(HSLError):
    """Gemini rejected the API key (invalid or revoked)."""
    code        = 401
    description = "Gemini authentication failed. The API key is invalid or has been revoked."
    http_status = 502

class GeminiPermissionError(HSLError):
    """The API key does not have permission to use the requested model or feature."""
    code        = 402
    description = "The configured API key does not have permission to access this Gemini model or feature."
    http_status = 502

class GeminiRateLimitError(HSLError):
    """Gemini rate limit or quota exhausted."""
    code        = 403
    description = "Gemini rate limit or quota exhausted. Retry after a short delay."
    http_status = 429

class GeminiResourceExhaustedError(HSLError):
    """Monthly or project-level quota has been fully consumed."""
    code        = 404
    description = "Gemini project quota has been exhausted. Check your Google Cloud billing and quota settings."
    http_status = 429

class GeminiServerError(HSLError):
    """Gemini returned a 5xx-class error (overloaded, internal fault)."""
    code        = 405
    description = "Gemini service is temporarily unavailable. Retry after a short delay."
    http_status = 502

class GeminiNetworkError(HSLError):
    """A network-level failure prevented the Gemini request from completing."""
    code        = 406
    description = "Could not reach the Gemini API due to a network error."
    http_status = 502

class GeminiEmptyResponseError(HSLError):
    """Gemini returned a response but with no structured (parsed) output."""
    code        = 407
    description = "Gemini returned an empty or unstructured response. Check document quality or model configuration."
    http_status = 422

class GeminiBlockedError(HSLError):
    """Gemini blocked the request due to safety filters."""
    code        = 408
    description = "Gemini blocked the request. The document may contain content that triggered safety filters."
    http_status = 422

class GeminiInvalidRequestError(HSLError):
    """The request payload was rejected by Gemini (bad schema, unsupported mime type, etc.)."""
    code        = 409
    description = "Gemini rejected the request due to an invalid payload."
    http_status = 500

class GeminiUnknownError(HSLError):
    """An unrecognised error was returned by the Gemini API."""
    code        = 410
    description = "An unexpected error was returned by the Gemini API."
    http_status = 502


# ---------------------------------------------------------------------------
# 5xx — API / request errors
# ---------------------------------------------------------------------------

class UnsupportedMediaTypeError(HSLError):
    """The uploaded file is not a PDF."""
    code        = 501
    description = "Unsupported file type. Only PDF files are accepted."
    http_status = 415

class EmptyUploadError(HSLError):
    """The uploaded file contains no bytes."""
    code        = 502
    description = "Uploaded file is empty."
    http_status = 400

class RequestValidationError(HSLError):
    """Generic request-level validation failure not covered by a more specific code."""
    code        = 503
    description = "Request validation failed."
    http_status = 400


# ---------------------------------------------------------------------------
# Gemini exception classifier
# ---------------------------------------------------------------------------

def classify_gemini_error(exc: Exception) -> HSLError:
    """
    Inspect a raw exception raised by the google-genai SDK and return the
    most appropriate HSLError subclass instance.

    The google-genai SDK raises google.api_core.exceptions.GoogleAPICallError
    subclasses for most failures. We classify by status code and message
    content rather than importing private SDK symbols, so the mapping stays
    stable across SDK versions.

    Args:
        exc (Exception): The raw exception caught from a Gemini API call or
                         client initialisation.

    Returns:
        HSLError: The matching HSLError subclass, with detail set to the
                  stringified original exception.

    Example:
        try:
            response = client.models.generate_content(...)
        except Exception as exc:
            raise classify_gemini_error(exc)
    """
    detail = str(exc)
    detail_lower = detail.lower()
    exc_type = type(exc).__name__.lower()

    # --- Connection / network failures ---
    if any(k in exc_type for k in ("connection", "timeout", "transport", "network")):
        return GeminiNetworkError(detail=detail)

    if any(k in detail_lower for k in ("connection", "timed out", "network", "socket", "ssl")):
        return GeminiNetworkError(detail=detail)

    # --- Auth / permission ---
    # google.api_core status codes: UNAUTHENTICATED=16, PERMISSION_DENIED=7
    if any(k in detail_lower for k in ("api key not valid", "invalid api key", "unauthenticated", "api_key_invalid")):
        return GeminiAuthError(detail=detail)

    if any(k in detail_lower for k in ("permission_denied", "permission denied", "forbidden", "does not have permission")):
        return GeminiPermissionError(detail=detail)

    # --- Quota / rate limits ---
    # RESOURCE_EXHAUSTED=8
    if any(k in detail_lower for k in ("quota_exceeded", "quota exceeded", "resource_exhausted", "billing")):
        return GeminiResourceExhaustedError(detail=detail)

    if any(k in detail_lower for k in ("rate_limit", "rate limit", "too many requests", "requests per minute", "429")):
        return GeminiRateLimitError(detail=detail)

    # --- Safety / blocked ---
    if any(k in detail_lower for k in ("safety", "blocked", "harm", "finish_reason: safety")):
        return GeminiBlockedError(detail=detail)

    # --- Invalid request ---
    if any(k in detail_lower for k in ("invalid_argument", "invalid argument", "bad request", "400")):
        return GeminiInvalidRequestError(detail=detail)

    # --- Server / overload ---
    if any(k in detail_lower for k in ("internal", "unavailable", "overloaded", "503", "500", "server error")):
        return GeminiServerError(detail=detail)

    # --- Fallback ---
    return GeminiUnknownError(detail=detail)