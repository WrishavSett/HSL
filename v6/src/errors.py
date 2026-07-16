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
    4xx  Gemini / LLM errors    — grouped by failure domain (see table below)
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

class GeminiNetworkError(HSLError):
    """A network-level failure prevented the Gemini request from completing."""
    code        = 400
    description = "Could not reach the Gemini API due to a network error."
    http_status = 502

class GeminiAuthError(HSLError):
    """Gemini rejected the API key (invalid or revoked)."""
    code        = 401
    description = "Gemini authentication failed. The API key is invalid or has been revoked."
    http_status = 502

class GeminiLeakedAPIKeyError(HSLError):
    """
    Gemini rejected the request because the configured API key was
    identified as publicly leaked and has been proactively blocked by
    Google.
    """
    code        = 402
    description = (
        "The configured Gemini API key was reported as leaked and has been "
        "blocked. Generate a new key in Google AI Studio and update "
        "GEMINI_API_KEY."
    )
    http_status = 502

class GeminiPermissionError(HSLError):
    """The API key does not have permission to use the requested model or feature."""
    code        = 403
    description = "The configured API key does not have permission to access this Gemini model or feature."
    http_status = 502

class GeminiInvalidRequestError(HSLError):
    """The request payload was rejected by Gemini (bad schema, unsupported mime type, etc.)."""
    code        = 404
    description = "Gemini rejected the request due to an invalid payload."
    http_status = 500

class GeminiFailedPreconditionError(HSLError):
    """
    Gemini returned 400 FAILED_PRECONDITION — most commonly because the free
    tier is not available in the caller's region and billing has not been
    enabled on the Google AI Studio / Cloud project.
    """
    code        = 405
    description = (
        "Gemini rejected the request because a precondition was not met "
        "(for example, the free tier is unavailable in this region and "
        "billing has not been enabled on the project)."
    )
    http_status = 400

class GeminiModelNotFoundError(HSLError):
    """
    Gemini returned 404 NOT_FOUND for the model or a referenced resource —
    typically an unsupported/misspelled model name, a deleted tuned model,
    or a missing file/endpoint referenced in the request.
    """
    code        = 406
    description = (
        "The requested Gemini model or referenced resource was not found. "
        "Check GEMINI_MODEL_NAME and confirm the model is supported."
    )
    http_status = 500

class GeminiRateLimitError(HSLError):
    """Gemini rate limit exceeded (requests per minute/day)."""
    code        = 407
    description = "Gemini rate limit or quota exhausted. Retry after a short delay."
    http_status = 429

class GeminiResourceExhaustedError(HSLError):
    """Monthly or project-level quota has been fully consumed."""
    code        = 408
    description = "Gemini project quota has been exhausted. Check your Google Cloud billing and quota settings."
    http_status = 429

class GeminiCancelledError(HSLError):
    """
    Gemini returned 499 CANCELLED — the operation was cancelled, typically
    because the client closed the connection before the API finished
    responding (e.g. a client-side timeout).
    """
    code        = 409
    description = (
        "The request to Gemini was cancelled before it completed, typically "
        "because the client closed the connection or a timeout elapsed."
    )
    http_status = 499

class GeminiDeadlineExceededError(HSLError):
    """
    Gemini returned 504 DEADLINE_EXCEEDED — the server accepted the request
    but could not finish processing it within the deadline, usually because
    the prompt or context is too large.
    """
    code        = 410
    description = (
        "Gemini could not finish processing the request within the deadline. "
        "The prompt or document may be too large; consider raising the "
        "client timeout or reducing input size."
    )
    http_status = 504

class GeminiServerError(HSLError):
    """Gemini returned a 5xx-class error (overloaded, internal fault)."""
    code        = 411
    description = "Gemini service is temporarily unavailable. Retry after a short delay."
    http_status = 502

class GeminiBlockedError(HSLError):
    """Gemini blocked the request due to safety filters."""
    code        = 412
    description = "Gemini blocked the request. The document may contain content that triggered safety filters."
    http_status = 422

class GeminiRecitationError(HSLError):
    """
    Gemini stopped generation with finish_reason RECITATION — the output
    closely resembled training data and was withheld.
    """
    code        = 413
    description = (
        "Gemini withheld its response because the output closely resembled "
        "existing training data (finish_reason=RECITATION)."
    )
    http_status = 422

class GeminiEmptyResponseError(HSLError):
    """Gemini returned a response but with no structured (parsed) output."""
    code        = 414
    description = "Gemini returned an empty or unstructured response. Check document quality or model configuration."
    http_status = 422

class GeminiUnknownError(HSLError):
    """An unrecognised error was returned by the Gemini API."""
    code        = 415
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

    The google-genai SDK (import: `from google.genai import errors`) raises
    `errors.ClientError` for 4xx responses and `errors.ServerError` for 5xx
    responses, both subclasses of `errors.APIError`, each carrying a `.code`
    attribute with the HTTP status returned by the backend (see
    https://ai.google.dev/gemini-api/docs/troubleshooting for the canonical
    status table). When that attribute is available we classify on it
    directly; otherwise (older SDKs, unrelated exception types, or statuses
    the table doesn't disambiguate on code alone, like 400/404/429 which
    each map to more than one HSL error) we fall back to matching on the
    stringified message. This keeps the mapping correct across SDK versions
    without importing private symbols.

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

    # The google-genai SDK's ClientError/ServerError exceptions carry a
    # `.code` attribute with the raw HTTP status. Prefer it when present.
    status_code = getattr(exc, "code", None)
    if not isinstance(status_code, int):
        status_code = None

    # Network / connection errors
    if any(k in exc_type for k in ("connection", "timeout", "transport", "network")):
        return GeminiNetworkError(detail=detail)

    if any(k in detail_lower for k in ("connection", "timed out", "network", "socket", "ssl")):
        return GeminiNetworkError(detail=detail)

    # Authentication
    if status_code == 401 or any(k in detail_lower for k in ("api key not valid", "invalid api key", "unauthenticated", "api_key_invalid")):
        return GeminiAuthError(detail=detail)

    # Leaked API key
    if "reported as leaked" in detail_lower or ("leaked" in detail_lower and "api key" in detail_lower):
        return GeminiLeakedAPIKeyError(detail=detail)

    # Permission denied
    if status_code == 403 or any(k in detail_lower for k in ("permission_denied", "permission denied", "forbidden", "does not have permission")):
        return GeminiPermissionError(detail=detail)

    # Invalid request
    if status_code == 400 or any(k in detail_lower for k in ("invalid_argument", "invalid argument", "bad request")):
        return GeminiInvalidRequestError(detail=detail)

    # Failed precondition
    if any(k in detail_lower for k in ("failed_precondition", "failed precondition", "free tier is not available", "enable billing")):
        return GeminiFailedPreconditionError(detail=detail)

    # Model / resource not found
    if status_code == 404 or any(k in detail_lower for k in ("not_found", "not found", "no such model", "does not exist")):
        return GeminiModelNotFoundError(detail=detail)

    # Rate limit
    if status_code == 429 or any(k in detail_lower for k in ("rate_limit", "rate limit", "too many requests", "requests per minute", "resource_exhausted")):
        return GeminiRateLimitError(detail=detail)

    # Resource exhausted
    if any(k in detail_lower for k in ("quota_exceeded", "quota exceeded", "project quota", "spend limit", "billing account")):
        return GeminiResourceExhaustedError(detail=detail)

    # Cancelled
    if status_code == 499 or "cancelled" in detail_lower or "canceled" in detail_lower:
        return GeminiCancelledError(detail=detail)

    # Deadline exceeded
    if status_code == 504 or any(k in detail_lower for k in ("deadline_exceeded", "deadline exceeded")):
        return GeminiDeadlineExceededError(detail=detail)

    # Server error
    if status_code in (500, 503) or any(k in detail_lower for k in ("internal", "unavailable", "overloaded", "server error")):
        return GeminiServerError(detail=detail)

    # Safety blocked
    if any(k in detail_lower for k in ("safety", "blocked", "harm", "finish_reason: safety")):
        return GeminiBlockedError(detail=detail)

    # Recitation
    if any(k in detail_lower for k in ("recitation", "finish_reason: recitation", "finish_reason=recitation")):
        return GeminiRecitationError(detail=detail)

    # Fallback
    return GeminiUnknownError(detail=detail)