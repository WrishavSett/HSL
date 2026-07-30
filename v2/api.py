#!/usr/bin/python3
"""
api.py
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, File as FastAPIFile, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gemini_client import _DEFAULT_CONFIG_PATH, GeminiClient
from helper import cleanup_temp_file, load_config, resolve_paths, _TEMP_DIR
from error import HSLBaseError, UnsupportedMediaTypeError, EmptyFileError, FileTooLargeError, FileSaveError

# ---------------------------------------------------------------------------
# Import logger
# ---------------------------------------------------------------------------

from logger import get_logger
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Initialise GeminiClient and load extraction config
# ---------------------------------------------------------------------------

_client = GeminiClient()
_, _, _, _fields_of_interest = load_config(_DEFAULT_CONFIG_PATH)

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def make_response(
    success: bool,
    code: int,
    message: str | None = None,
    error: str | None = None,
    data=None,
) -> JSONResponse:
    return JSONResponse(
        status_code=code,
        content={
            "success": success,
            "code":    code,
            "message": message,
            "error":   error,
            "data":    data,
        },
    )

# ---------------------------------------------------------------------------
# Lifespan — startup and shutdown logging
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("HSL Invoice Extraction API is ready.")
    yield
    log.info("HSL Invoice Extraction API is shutting down.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="HSL Invoice Extraction API",
    description="Accepts a raw PDF body and returns structured JSON extracted by Gemini.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_upload(pdf_bytes: bytes) -> str:
    os.makedirs(_TEMP_DIR, exist_ok=True)
    temp_path = os.path.join(_TEMP_DIR, f"{uuid.uuid4().hex}_upload.pdf")

    try:
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
        log.debug(f"Saved uploaded PDF to temporary file: {temp_path}")
    except OSError as exc:
        log.error(f"Failed to write temporary PDF file at {temp_path}: {exc}")
        raise FileSaveError(temp_path, str(exc)) from exc

    return temp_path

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", summary="Health check")
async def health_check() -> JSONResponse:
    return make_response(success=True, code=200, message="HSL Invoice Extraction API is running.")


@app.post(
    "/extract",
    summary="Extract structured data from a PDF invoice",
    response_description="Structured JSON: company_name, invoice_no, po_no, subtotal",
)
async def extract(File: UploadFile = FastAPIFile(...)) -> JSONResponse:
    # 1. Validate Content-Type / filename extension
    is_pdf_content_type = File.content_type in ("application/pdf", "application/octet-stream")
    is_pdf_extension    = (File.filename or "").lower().endswith(".pdf")
    if not is_pdf_content_type and not is_pdf_extension:
        err = UnsupportedMediaTypeError(File.content_type, File.filename or "")
        log.error(err.error)
        return make_response(success=False, code=err.code, message=err.message, error=err.error)

    # 2. Read uploaded file
    pdf_bytes = await File.read()
    if not pdf_bytes:
        err = EmptyFileError()
        log.error(err.error)
        return make_response(success=False, code=err.code, message=err.message, error=err.error)
    if len(pdf_bytes) > _MAX_UPLOAD_SIZE:
        err = FileTooLargeError(_MAX_UPLOAD_SIZE)
        log.error(err.error)
        return make_response(success=False, code=err.code, message=err.message, error=err.error)

    # 3. Save upload → run extraction → always clean up temp file
    temp_pdf: str = ""
    try:
        temp_pdf = _save_upload(pdf_bytes)
        result   = _client.extract_invoice_data(temp_pdf)

    except HSLBaseError as exc:
        return make_response(success=False, code=exc.code, message=exc.message, error=exc.error)

    except Exception as exc:
        log.error(f"Unexpected error: {exc}")
        return make_response(
            success=False,
            code=500,
            message="Encountered unexpected error. Please try again.",
            error=f"Unexpected error: {exc}",
        )

    finally:
        if temp_pdf:
            cleanup_temp_file(temp_pdf)

    # 4. Resolve fields of interest and return
    data = resolve_paths(result, _fields_of_interest)
    return make_response(
        success=True,
        code=200,
        message="Invoice data extracted successfully.",
        data=data,
    )