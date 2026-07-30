#!/usr/bin/python3
"""
error.py
"""

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class HSLBaseError(Exception):
    """Base class for all HSL Invoice Extraction pipeline errors.

    Attributes
    ----------
    message:  Client-facing string returned in ``message``.
    error:    Operator-facing detail logged and returned in ``error``.
    code:     HTTP status code.
    """

    def __init__(self, message: str, error: str, code: int = 500):
        super().__init__(error)
        self.message = message
        self.error   = error
        self.code    = code

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code}, "
            f"message={self.message!r}, "
            f"error={self.error!r})"
        )

# ---------------------------------------------------------------------------
# Config errors
# ---------------------------------------------------------------------------

class ConfigNotFoundError(HSLBaseError):
    """Config file does not exist at the given path."""

    def __init__(self, path: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Config file not found: {path!r}. Ensure the path is correct and the file exists.",
            code=500,
        )
        self.path = path


class ConfigInvalidJSONError(HSLBaseError):
    """Config file exists but contains invalid JSON."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Config file {path!r} contains invalid JSON. Parser error: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail


class ConfigMissingKeyError(HSLBaseError):
    """One or more required keys are absent from the config file."""

    def __init__(self, path: str, missing: list[str]):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Config file {path!r} is missing required key(s): {missing}.",
            code=500,
        )
        self.path    = path
        self.missing = missing


class ConfigValueError(HSLBaseError):
    """A config value fails type or content validation."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Config file {path!r} has an invalid value: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail

# ---------------------------------------------------------------------------
# Upload errors
# ---------------------------------------------------------------------------

class UnsupportedMediaTypeError(HSLBaseError):
    """Uploaded file is not a PDF."""

    def __init__(self, content_type: str, filename: str):
        super().__init__(
            message="Invalid file type. Please upload a PDF file.",
            error=f"Expected a PDF file. Got content-type {content_type!r} and filename {filename!r}.",
            code=415,
        )
        self.content_type = content_type
        self.filename     = filename


class EmptyFileError(HSLBaseError):
    """Uploaded file contains no bytes."""

    def __init__(self):
        super().__init__(
            message="The uploaded file is empty. Please upload a valid PDF file.",
            error="Uploaded file is empty.",
            code=400,
        )


class FileTooLargeError(HSLBaseError):
    """Uploaded file exceeds the configured size limit."""

    def __init__(self, max_bytes: int):
        super().__init__(
            message=f"File too large. Maximum allowed size is {max_bytes // (1024 * 1024)} MB.",
            error=f"Uploaded file exceeds maximum size of {max_bytes} bytes.",
            code=413,
        )
        self.max_bytes = max_bytes


class FileSaveError(HSLBaseError):
    """Temporary PDF file could not be written to disk."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Failed to write temporary PDF file at {path!r}: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail

# ---------------------------------------------------------------------------
# PDF conversion errors
# ---------------------------------------------------------------------------

class PDF2ImageNotInstalledError(HSLBaseError):
    """pdf2image package is not installed."""

    def __init__(self):
        super().__init__(
            message="Internal server error. Please try again.",
            error=(
                f"pdf2image is required for PDF support.\n"
                f"Install it with: pip install pdf2image\n"
                f"You also need Poppler on your system PATH:\n"
                f"  Ubuntu/Debian : sudo apt-get install poppler-utils\n"
                f"  macOS         : brew install poppler\n"
                f"  Windows       : download poppler and add its bin/ to PATH"
            ),
            code=500,
        )


class PDFNotFoundError(HSLBaseError):
    """PDF file does not exist at the given path."""

    def __init__(self, path: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"PDF file not found: {path!r}. Ensure the path is correct and the file exists.",
            code=500,
        )
        self.path = path


class PopplerNotInstalledError(HSLBaseError):
    """Poppler utilities are not installed or not on PATH."""

    def __init__(self):
        super().__init__(
            message="Internal server error. Please try again.",
            error=(
                "Poppler's pdfinfo utility was not found. "
                "Install Poppler and make sure its executables are on your PATH."
            ),
            code=500,
        )


class PDFPageCountError(HSLBaseError):
    """PDF page count could not be read."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="The uploaded PDF could not be processed. Ensure the file is not corrupted.",
            error=f"Could not read page count from {path!r}: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail


class PDFTooManyPagesError(HSLBaseError):
    """PDF exceeds the maximum allowed page count."""

    def __init__(self, page_count: int, max_pages: int):
        super().__init__(
            message=f"The uploaded PDF exceeds the maximum allowed page limit of {max_pages}. Please upload a shorter document.",
            error=f"PDF has {page_count} pages, which exceeds the limit of {max_pages}.",
            code=413,
        )
        self.page_count = page_count
        self.max_pages  = max_pages


class PDFConversionError(HSLBaseError):
    """PDF-to-image conversion failed for an unexpected reason."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="The uploaded PDF could not be processed. Ensure the file is not corrupted.",
            error=f"PDF conversion failed for {path!r}: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail

# ---------------------------------------------------------------------------
# Gemini client errors
# ---------------------------------------------------------------------------

class GoogleGenAINotInstalledError(HSLBaseError):
    """google-genai package is not installed."""

    def __init__(self):
        super().__init__(
            message="Internal server error. Please try again.",
            error="google-genai is required for Gemini support. Install it with: pip install google-genai.",
            code=500,
        )


class GeminiMissingAPIKeyError(HSLBaseError):
    """GEMINI_API_KEY environment variable is not set."""

    def __init__(self):
        super().__init__(
            message="Internal server error. Please try again.",
            error="GEMINI_API_KEY environment variable is not set.",
            code=500,
        )


class GeminiMissingModelNameError(HSLBaseError):
    """GEMINI_MODEL_NAME environment variable is not set."""

    def __init__(self):
        super().__init__(
            message="Internal server error. Please try again.",
            error="GEMINI_MODEL_NAME environment variable is not set.",
            code=500,
        )


class GeminiAuthError(HSLBaseError):
    """Gemini API key validation failed."""

    def __init__(self, detail: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Gemini API key validation failed: {detail}",
            code=500,
        )
        self.detail = detail


class GeminiModelNotFoundError(HSLBaseError):
    """Requested Gemini model is not available under the given API key."""

    def __init__(self, model_name: str, available: list[str]):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Gemini model {model_name!r} is not available. Available models: {available}",
            code=500,
        )
        self.model_name = model_name
        self.available  = available


class GeminiImageNotFoundError(HSLBaseError):
    """An image file passed to the Gemini API does not exist."""

    def __init__(self, path: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Image file not found: {path!r}. Ensure the path is correct and the file exists.",
            code=500,
        )
        self.path = path


class GeminiImageReadError(HSLBaseError):
    """An image file could not be read from disk."""

    def __init__(self, path: str, detail: str):
        super().__init__(
            message="Internal server error. Please try again.",
            error=f"Could not read image file {path!r}: {detail}",
            code=500,
        )
        self.path   = path
        self.detail = detail


class GeminiAPICallError(HSLBaseError):
    """Gemini API call failed."""

    def __init__(self, detail: str):
        super().__init__(
            message="Invoice extraction failed. Please try again.",
            error=f"Gemini API call failed: {detail}",
            code=500,
        )
        self.detail = detail


class GeminiEmptyResponseError(HSLBaseError):
    """Gemini returned a response but structured output could not be parsed."""

    def __init__(self):
        super().__init__(
            message="Invoice extraction failed. The document may be unreadable or unsupported.",
            error=(
                "Gemini returned no structured output. "
                "Check document quality, page count, or model configuration."
            ),
            code=500,
        )